#!/usr/bin/env python3
"""Extract Tier 1 and Tier 2 corpus questions from Elasticsearch.

Two extraction passes:

1. **Tier 1 (existence)**: LLM spans where agents flagged components as
   absent from the architecture-context ("absent from", "not in the
   architecture", etc.). These become "Is X a RHOAI component?" questions.

2. **Tier 2 (fact extraction)**: tool_Read spans that successfully read
   architecture-context files. The file path + surrounding LLM context
   indicate what fact the agent was looking for, generating "What port
   does X use?" style questions.

Usage:
    python scripts/extract_corpus_tier12.py \
        [--elastic-uri http://elasticsearch:9200] \
        [--output var/benchmarks/arch-context/raw/tier12-extracted.jsonl] \
        [--dry-run]

Environment:
    ELASTICSEARCH_URI  — Elasticsearch endpoint (default: http://elasticsearch:9200)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan


ELASTIC_URI = os.getenv("ELASTICSEARCH_URI", "http://elasticsearch:9200")
SPANS_INDEX = "mlflow-spans"

_COMPONENT_NAME_RE = re.compile(
    r"(?:component|service|operator|controller)\s+['\"]?([a-z][a-z0-9_-]+)['\"]?",
    re.IGNORECASE,
)
_ARCH_FILE_RE = re.compile(
    r"architecture/([^/]+)/([^/]+)\.md"
)
_FACT_KEYWORDS = {
    "port": re.compile(r"\b(?:port|endpoint|listen)\b", re.IGNORECASE),
    "crd": re.compile(r"\b(?:CRD|CustomResourceDefinition|custom resource)\b", re.IGNORECASE),
    "api": re.compile(r"\b(?:API|endpoint|REST|gRPC|HTTP)\b", re.IGNORECASE),
    "dependency": re.compile(r"\b(?:depend|require|upstream|downstream)\b", re.IGNORECASE),
    "rbac": re.compile(r"\b(?:RBAC|role|permission|ClusterRole|ServiceAccount)\b", re.IGNORECASE),
    "metric": re.compile(r"\b(?:metric|prometheus|monitor|scrape)\b", re.IGNORECASE),
    "config": re.compile(r"\b(?:config|env|environment|parameter|setting)\b", re.IGNORECASE),
}


def query_absent_components(es: Elasticsearch) -> list[dict]:
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"name": "llm"}},
                    {
                        "bool": {
                            "should": [
                                {"match_phrase": {"outputs": "absent from"}},
                                {"match_phrase": {"outputs": "not in the architecture"}},
                                {"match_phrase": {"outputs": "not documented in"}},
                                {"match_phrase": {"outputs": "not in RHOAI"}},
                                {"match_phrase": {"outputs": "not in the component inventory"}},
                                {"match_phrase": {"outputs": "not found in the architecture"}},
                                {"match_phrase": {"outputs": "no component doc"}},
                                {"match_phrase": {"outputs": "cannot find"}},
                                {"match_phrase": {"outputs": "not a RHOAI component"}},
                                {"match_phrase": {"outputs": "no documentation for"}},
                                {"match_phrase": {"outputs": "is not listed"}},
                            ],
                        }
                    },
                ]
            }
        },
        "_source": ["trace_id", "span_id", "issue_keys", "outputs"],
    }
    return [hit["_source"] for hit in scan(es, index=SPANS_INDEX, query=query)]


def query_successful_reads(es: Elasticsearch) -> list[dict]:
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"name": "tool_Read"}},
                    {"match_phrase": {"inputs": "architecture-context"}},
                ],
                "must_not": [
                    {"match_phrase": {"outputs": "No such file"}},
                    {"match_phrase": {"outputs": "Permission denied"}},
                    {"match_phrase": {"outputs": "cannot access"}},
                ],
            }
        },
        "_source": ["trace_id", "span_id", "issue_keys", "inputs", "outputs"],
    }
    return [hit["_source"] for hit in scan(es, index=SPANS_INDEX, query=query)]


def extract_component_name(text: str) -> str | None:
    match = _COMPONENT_NAME_RE.search(text)
    if match:
        return match.group(1)
    return None


def extract_tier1_questions(spans: list[dict]) -> list[dict]:
    records = []
    for span in spans:
        output = span.get("outputs", "")
        component = extract_component_name(output)
        if not component:
            words = output.split()
            for i, w in enumerate(words):
                if w.lower() in ("absent", "missing", "not"):
                    start = max(0, i - 5)
                    context = " ".join(words[start : i + 5])
                    component = extract_component_name(context)
                    if component:
                        break

        if not component or len(component) < 3:
            continue

        records.append({
            "tier": 1,
            "category": "inventory-lookup",
            "question": f"Is {component} a RHOAI component?",
            "component": component,
            "trace_id": span.get("trace_id", ""),
            "issue_keys": span.get("issue_keys", []),
            "raw_output": output[:500],
        })
    return records


def classify_fact_type(text: str) -> str:
    for fact_type, pattern in _FACT_KEYWORDS.items():
        if pattern.search(text):
            return fact_type
    return "general"


def extract_tier2_questions(spans: list[dict]) -> list[dict]:
    records = []
    for span in spans:
        inputs_text = span.get("inputs", "")
        outputs_text = span.get("outputs", "")

        match = _ARCH_FILE_RE.search(inputs_text)
        if not match:
            continue

        version = match.group(1)
        component = match.group(2)
        file_path = f"architecture/{version}/{component}.md"

        fact_type = classify_fact_type(outputs_text[:2000])

        question_templates = {
            "port": f"What ports does {component} expose?",
            "crd": f"What CRDs does {component} manage?",
            "api": f"What API endpoints does {component} provide?",
            "dependency": f"What are the dependencies of {component}?",
            "rbac": f"What RBAC permissions does {component} require?",
            "metric": f"What metrics does {component} expose?",
            "config": f"What configuration options does {component} support?",
            "general": f"What are the key technical details of {component}?",
        }

        records.append({
            "tier": 2,
            "category": "fact-extraction",
            "question": question_templates.get(fact_type, question_templates["general"]),
            "component": component,
            "version": version,
            "fact_type": fact_type,
            "source_file": file_path,
            "trace_id": span.get("trace_id", ""),
            "issue_keys": span.get("issue_keys", []),
            "raw_input": inputs_text[:500],
        })
    return records


def deduplicate(records: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in records:
        key = (
            r.get("component", ""),
            r.get("version", ""),
            r.get("fact_type", r.get("category", "")),
        )
        if key not in seen:
            seen[key] = r
    return list(seen.values())


def main():
    parser = argparse.ArgumentParser(
        description="Extract Tier 1/2 questions from ES"
    )
    parser.add_argument(
        "--elastic-uri", default=ELASTIC_URI, help="Elasticsearch URI"
    )
    parser.add_argument(
        "--output",
        default="var/benchmarks/arch-context/raw/tier12-extracted.jsonl",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    es = Elasticsearch(args.elastic_uri)
    if not es.ping():
        print("ERROR: Cannot connect to Elasticsearch", file=sys.stderr)
        sys.exit(1)

    print(f"Extracting Tier 1 (existence) questions...")
    absent_spans = query_absent_components(es)
    print(f"  Found {len(absent_spans)} LLM spans with absent-component signals")
    tier1 = extract_tier1_questions(absent_spans)
    print(f"  Extracted {len(tier1)} Tier 1 questions")

    print(f"\nExtracting Tier 2 (fact extraction) questions...")
    read_spans = query_successful_reads(es)
    print(f"  Found {len(read_spans)} successful architecture-context reads")
    tier2 = extract_tier2_questions(read_spans)
    print(f"  Extracted {len(tier2)} Tier 2 questions")

    all_records = tier1 + tier2
    deduped = deduplicate(all_records)
    tier1_count = sum(1 for r in deduped if r["tier"] == 1)
    tier2_count = sum(1 for r in deduped if r["tier"] == 2)
    print(f"\nAfter dedup: {len(deduped)} unique ({tier1_count} T1, {tier2_count} T2)")

    if args.dry_run:
        for r in deduped[:10]:
            print(f"  [T{r['tier']}] Q: {r['question']}")
            print(f"    component: {r.get('component', 'n/a')}")
        return

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for r in deduped:
            f.write(json.dumps(r) + "\n")
    print(f"Wrote {len(deduped)} records to {output_path}")


if __name__ == "__main__":
    main()
