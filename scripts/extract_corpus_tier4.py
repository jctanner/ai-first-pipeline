#!/usr/bin/env python3
"""Extract Tier 4 (navigation) corpus questions from Elasticsearch.

Queries mlflow-spans for tool_Bash spans where agents tried to access
architecture-context paths and got errors (No such file, DIR NOT FOUND,
cannot access). These represent real navigation failures that become
benchmark questions testing directory structure awareness.

Usage:
    python scripts/extract_corpus_tier4.py \
        [--elastic-uri http://elasticsearch:9200] \
        [--output var/benchmarks/arch-context/raw/tier4-extracted.jsonl] \
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

_PATH_RE = re.compile(
    r"(?:architecture-context|\.context/architecture-context)"
    r"(?:/[^\s'\"`,;)\]}>]+)+"
)
_COMPONENT_RE = re.compile(
    r"architecture/[^/]+/([^/.]+)\.md"
)
_VERSION_RE = re.compile(
    r"architecture/(rhoai-[^/]+)"
)
_ERROR_PATTERNS = [
    ("not_found", re.compile(r"No such file or directory", re.IGNORECASE)),
    ("dir_not_found", re.compile(r"DIR NOT FOUND", re.IGNORECASE)),
    ("cannot_access", re.compile(r"cannot access", re.IGNORECASE)),
    ("not_a_directory", re.compile(r"Not a directory", re.IGNORECASE)),
    ("permission_denied", re.compile(r"Permission denied", re.IGNORECASE)),
]


def query_failed_paths(es: Elasticsearch) -> list[dict]:
    query = {
        "query": {
            "bool": {
                "must": [
                    {
                        "bool": {
                            "should": [
                                {"term": {"name": "tool_Bash"}},
                                {"term": {"name": "tool_Read"}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                    {"match_phrase": {"inputs": "architecture-context"}},
                    {
                        "bool": {
                            "should": [
                                {"match_phrase": {"outputs": "No such file"}},
                                {"match_phrase": {"outputs": "DIR NOT FOUND"}},
                                {"match_phrase": {"outputs": "cannot access"}},
                                {"match_phrase": {"outputs": "Not a directory"}},
                                {"match_phrase": {"outputs": "Permission denied"}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                ]
            }
        },
        "_source": ["trace_id", "span_id", "issue_keys", "inputs", "outputs"],
    }
    return [hit["_source"] for hit in scan(es, index=SPANS_INDEX, query=query)]


def normalize_path(path: str) -> str:
    path = path.lstrip("./")
    path = re.sub(r"^\.context/", "", path)
    path = re.sub(r"//+", "/", path)
    return path.rstrip("/")


def classify_error(output: str) -> str:
    for name, pattern in _ERROR_PATTERNS:
        if pattern.search(output):
            return name
    return "unknown"


def extract_question(span: dict) -> dict | None:
    inputs_text = span.get("inputs", "")
    outputs_text = span.get("outputs", "")

    paths = _PATH_RE.findall(inputs_text + " " + outputs_text)
    if not paths:
        return None

    raw_path = paths[0]
    norm_path = normalize_path(raw_path)

    component_match = _COMPONENT_RE.search(norm_path)
    component = component_match.group(1) if component_match else None

    version_match = _VERSION_RE.search(norm_path)
    version = version_match.group(1) if version_match else None

    error_type = classify_error(outputs_text)

    if component and version:
        question = (
            f"Where is the {component} component doc in the {version} "
            f"architecture directory?"
        )
    elif component:
        question = (
            f"Where is the {component} component doc in the architecture "
            f"directory?"
        )
    elif "components/" in norm_path:
        question = (
            "Does the architecture-context directory have a components/ "
            "subdirectory?"
        )
    elif version:
        question = (
            f"What is the correct path structure for {version} architecture "
            f"docs?"
        )
    else:
        last_segment = norm_path.rstrip("/").rsplit("/", 1)[-1]
        question = f"Where can {last_segment} be found in the architecture-context?"

    return {
        "tier": 4,
        "category": "navigation",
        "question": question,
        "failed_path": norm_path,
        "error_type": error_type,
        "component": component,
        "version": version,
        "trace_id": span.get("trace_id", ""),
        "issue_keys": span.get("issue_keys", []),
        "raw_input": inputs_text[:500],
        "raw_output": outputs_text[:500],
    }


def deduplicate(records: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in records:
        key = (r.get("failed_path", ""), r.get("error_type", ""))
        if key not in seen:
            seen[key] = r
    return list(seen.values())


def main():
    parser = argparse.ArgumentParser(
        description="Extract Tier 4 navigation questions from ES"
    )
    parser.add_argument(
        "--elastic-uri", default=ELASTIC_URI, help="Elasticsearch URI"
    )
    parser.add_argument(
        "--output",
        default="var/benchmarks/arch-context/raw/tier4-extracted.jsonl",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    es = Elasticsearch(args.elastic_uri)
    if not es.ping():
        print("ERROR: Cannot connect to Elasticsearch", file=sys.stderr)
        sys.exit(1)

    print(f"Querying {SPANS_INDEX} for failed path lookups...")
    spans = query_failed_paths(es)
    print(f"  Found {len(spans)} spans with path errors")

    records = []
    for span in spans:
        rec = extract_question(span)
        if rec:
            records.append(rec)
    print(f"  Extracted {len(records)} questions")

    deduped = deduplicate(records)
    print(f"  After dedup: {len(deduped)} unique questions")

    if args.dry_run:
        for r in deduped[:10]:
            print(f"  Q: {r['question']}")
            print(f"    path: {r['failed_path']}  error: {r['error_type']}")
        return

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for r in deduped:
            f.write(json.dumps(r) + "\n")
    print(f"Wrote {len(deduped)} records to {output_path}")


if __name__ == "__main__":
    main()
