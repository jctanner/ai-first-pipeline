#!/usr/bin/env python3
"""Extract Tier 3 (cross-component integration) corpus questions from Elasticsearch.

Queries mlflow-spans for tool_Skill spans matching architecture-review
and strategy-review sub-skills. These spans contain claim-verification
pairs where agents cross-referenced multiple component docs — ideal for
generating questions that test multi-component reasoning.

Usage:
    python scripts/extract_corpus_tier3.py \
        [--elastic-uri http://elasticsearch:9200] \
        [--output var/benchmarks/arch-context/raw/tier3-extracted.jsonl] \
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

_COMPONENT_RE = re.compile(
    r"\b([a-z][a-z0-9_-]*(?:-[a-z0-9]+)+)\b"
)
_CLAIM_MARKERS = [
    re.compile(r"(?:can|does|will|should)\s+\w+\s+(?:use|support|integrate|interact|connect|trigger|invoke)", re.IGNORECASE),
    re.compile(r"(?:how|what)\s+(?:is|are|does)\s+the\s+(?:interaction|relationship|integration|flow|path)", re.IGNORECASE),
    re.compile(r"(?:request|data|event)\s+(?:path|flow|pipeline)\s+(?:from|through|between)", re.IGNORECASE),
    re.compile(r"(?:cross-component|multi-component|inter-component|end-to-end)", re.IGNORECASE),
]
_ARCH_FILE_RE = re.compile(r"architecture/[^/]+/([^/.]+)\.md")


def query_review_spans(es: Elasticsearch) -> list[dict]:
    query = {
        "query": {
            "bool": {
                "should": [
                    {
                        "bool": {
                            "must": [
                                {"term": {"name": "tool_Skill"}},
                                {
                                    "bool": {
                                        "should": [
                                            {"match": {"inputs": "architecture-review"}},
                                            {"match": {"inputs": "architecture.review"}},
                                            {"match": {"inputs": "feasibility"}},
                                        ],
                                    }
                                },
                            ]
                        }
                    },
                    {
                        "bool": {
                            "must": [
                                {"term": {"name": "llm"}},
                                {"match_phrase": {"inputs": "architecture-context"}},
                                {
                                    "bool": {
                                        "should": [
                                            {"match_phrase": {"outputs": "cross-component"}},
                                            {"match_phrase": {"outputs": "integration"}},
                                            {"match_phrase": {"outputs": "dependency between"}},
                                            {"match_phrase": {"outputs": "communicates with"}},
                                            {"match_phrase": {"outputs": "interacts with"}},
                                        ],
                                        "minimum_should_match": 1,
                                    }
                                },
                            ]
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        },
        "_source": ["trace_id", "span_id", "issue_keys", "inputs", "outputs"],
    }
    return [hit["_source"] for hit in scan(es, index=SPANS_INDEX, query=query)]


def query_multi_read_traces(es: Elasticsearch) -> list[dict]:
    """Find traces that read 2+ different architecture-context component docs."""
    from collections import defaultdict

    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"name": "tool_Read"}},
                    {"match_phrase": {"inputs": "architecture-context"}},
                ],
                "must_not": [
                    {"match_phrase": {"outputs": "No such file"}},
                ],
            }
        },
    }
    traces = defaultdict(set)
    for hit in scan(es, index=SPANS_INDEX, query=query, _source=["trace_id", "inputs"]):
        src = hit["_source"]
        traces[src.get("trace_id", "")].add(src.get("inputs", ""))
    multi_traces = []
    for trace_id, inputs_set in traces.items():
        if len(inputs_set) >= 2:
            multi_traces.append({"trace_id": trace_id, "read_count": len(inputs_set)})
    return multi_traces


def extract_components_from_text(text: str) -> list[str]:
    file_matches = _ARCH_FILE_RE.findall(text)
    if file_matches:
        return list(dict.fromkeys(file_matches))

    candidates = _COMPONENT_RE.findall(text)
    known_noise = {
        "architecture-context", "arch-context", "rhoai-3", "rhoai-4",
        "early-access", "current-ga", "latest-released", "tool-read",
        "tool-bash", "tool-skill", "match-phrase", "must-not",
    }
    return list(dict.fromkeys(
        c for c in candidates
        if c not in known_noise and len(c) > 3
    ))


def generate_question(components: list[str], context: str) -> str | None:
    if len(components) < 2:
        return None

    for marker in _CLAIM_MARKERS:
        match = marker.search(context)
        if match:
            start = max(0, match.start() - 50)
            end = min(len(context), match.end() + 100)
            snippet = context[start:end].strip()
            snippet = re.sub(r"\s+", " ", snippet)
            if len(snippet) > 20:
                if not snippet.endswith("?"):
                    snippet = snippet.rstrip(".") + "?"
                return snippet

    c1, c2 = components[0], components[1]
    return f"How do {c1} and {c2} interact in the RHOAI architecture?"


def extract_questions(spans: list[dict]) -> list[dict]:
    records = []
    for span in spans:
        inputs_text = span.get("inputs", "")
        outputs_text = span.get("outputs", "")
        combined = inputs_text + " " + outputs_text

        components = extract_components_from_text(combined)
        if len(components) < 2:
            continue

        question = generate_question(components, combined)
        if not question:
            continue

        records.append({
            "tier": 3,
            "category": "cross-component-integration",
            "question": question,
            "components": components[:5],
            "trace_id": span.get("trace_id", ""),
            "issue_keys": span.get("issue_keys", []),
            "raw_input": inputs_text[:500],
            "raw_output": outputs_text[:500],
        })
    return records


def deduplicate(records: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in records:
        key = (
            tuple(sorted(r.get("components", [])[:3])),
            r.get("category", ""),
        )
        if key not in seen:
            seen[key] = r
    return list(seen.values())


def main():
    parser = argparse.ArgumentParser(
        description="Extract Tier 3 cross-component questions from ES"
    )
    parser.add_argument(
        "--elastic-uri", default=ELASTIC_URI, help="Elasticsearch URI"
    )
    parser.add_argument(
        "--output",
        default="var/benchmarks/arch-context/raw/tier3-extracted.jsonl",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    es = Elasticsearch(args.elastic_uri)
    if not es.ping():
        print("ERROR: Cannot connect to Elasticsearch", file=sys.stderr)
        sys.exit(1)

    print("Extracting Tier 3 (cross-component) questions...")

    print("  Querying review/feasibility skill spans...")
    review_spans = query_review_spans(es)
    print(f"  Found {len(review_spans)} review spans")

    print("  Querying multi-component read traces...")
    multi_traces = query_multi_read_traces(es)
    print(f"  Found {len(multi_traces)} traces reading 2+ component docs")

    records = extract_questions(review_spans)
    print(f"  Extracted {len(records)} questions from review spans")

    deduped = deduplicate(records)
    print(f"  After dedup: {len(deduped)} unique questions")

    if args.dry_run:
        for r in deduped[:10]:
            print(f"  Q: {r['question']}")
            print(f"    components: {r['components']}")
        return

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for r in deduped:
            f.write(json.dumps(r) + "\n")
    print(f"Wrote {len(deduped)} records to {output_path}")


if __name__ == "__main__":
    main()
