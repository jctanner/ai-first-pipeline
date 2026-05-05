#!/usr/bin/env python3
"""Sync MLflow traces and spans into Elasticsearch.

Usage:
    uv run python scripts/sync_mlflow_to_elastic.py              # incremental
    uv run python scripts/sync_mlflow_to_elastic.py --full        # reindex all
    uv run python scripts/sync_mlflow_to_elastic.py --dry-run     # preview only
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import mlflow
import requests
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
ELASTIC_URI = os.getenv("ELASTICSEARCH_URI", "http://elasticsearch:9200")

TRACES_INDEX = "mlflow-traces"
SPANS_INDEX = "mlflow-spans"

_ISSUE_KEY_RE = re.compile(r"(?:RHOAIENG|RHAIRFE|RHAISTRAT)-\d+")

TRACES_MAPPING = {
    "mappings": {
        "properties": {
            "trace_id": {"type": "keyword"},
            "issue_keys": {"type": "keyword"},
            "status": {"type": "keyword"},
            "start_time": {"type": "date"},
            "duration_s": {"type": "float"},
            "cost_usd": {"type": "float"},
            "input_tokens": {"type": "integer"},
            "output_tokens": {"type": "integer"},
            "total_tokens": {"type": "integer"},
            "num_spans": {"type": "integer"},
            "session_id": {"type": "keyword"},
            "user": {"type": "keyword"},
            "claude_code_version": {"type": "keyword"},
            "prompt": {"type": "text"},
            "response": {"type": "text"},
        }
    }
}

SPANS_MAPPING = {
    "mappings": {
        "properties": {
            "trace_id": {"type": "keyword"},
            "span_id": {"type": "keyword"},
            "parent_id": {"type": "keyword"},
            "name": {"type": "keyword"},
            "span_type": {"type": "keyword"},
            "status": {"type": "keyword"},
            "start_time": {"type": "date"},
            "duration_ms": {"type": "long"},
            "inputs": {"type": "text"},
            "outputs": {"type": "text"},
            "tool_name": {"type": "keyword"},
            "issue_keys": {"type": "keyword"},
            "model": {"type": "keyword"},
            "error": {"type": "text"},
        }
    }
}


def _ts_to_iso(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _parse_json(raw):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_issue_keys(text):
    return list(dict.fromkeys(_ISSUE_KEY_RE.findall(text)))


def ensure_indices(es):
    for index, mapping in [(TRACES_INDEX, TRACES_MAPPING), (SPANS_INDEX, SPANS_MAPPING)]:
        if not es.indices.exists(index=index):
            es.indices.create(index=index, body=mapping)
            print(f"  Created index: {index}")


def get_high_water_mark(es):
    """Get the latest start_time from the traces index."""
    if not es.indices.exists(index=TRACES_INDEX):
        return 0
    try:
        result = es.search(
            index=TRACES_INDEX,
            body={
                "size": 0,
                "aggs": {"max_ts": {"max": {"field": "start_time"}}},
            },
        )
        val = result["aggregations"]["max_ts"]["value"]
        return int(val) if val else 0
    except Exception:
        return 0


def fetch_traces_from_mlflow(since_ms=0):
    """Fetch trace metadata from MLflow REST API, paginated."""
    all_traces = []
    url = f"{MLFLOW_URI}/api/2.0/mlflow/traces"
    page_token = None

    while True:
        params = {"experiment_ids": "0", "max_results": "100"}
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for t in data.get("traces", []):
            ts = t.get("timestamp_ms", 0)
            if ts > since_ms:
                all_traces.append(t)

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return all_traces


def parse_trace(raw_trace):
    """Parse a raw MLflow trace into an Elasticsearch document."""
    meta = {m["key"]: m["value"] for m in raw_trace.get("request_metadata", [])}

    inputs_raw = meta.get("mlflow.traceInputs", "")
    outputs_raw = meta.get("mlflow.traceOutputs", "")
    issue_keys = _extract_issue_keys(inputs_raw + outputs_raw)

    cost = _parse_json(meta.get("mlflow.trace.cost", "")) or {}
    tokens = _parse_json(meta.get("mlflow.trace.tokenUsage", "")) or {}
    size = _parse_json(meta.get("mlflow.trace.sizeStats", "")) or {}

    inputs_parsed = _parse_json(inputs_raw) or {}
    outputs_parsed = _parse_json(outputs_raw) or {}

    return {
        "trace_id": raw_trace["request_id"],
        "issue_keys": issue_keys,
        "status": raw_trace.get("status", ""),
        "start_time": _ts_to_iso(raw_trace.get("timestamp_ms")),
        "duration_s": round(raw_trace.get("execution_time_ms", 0) / 1000, 1),
        "cost_usd": round(cost.get("total_cost", 0), 4),
        "input_tokens": tokens.get("input_tokens", 0),
        "output_tokens": tokens.get("output_tokens", 0),
        "total_tokens": tokens.get("total_tokens", 0),
        "num_spans": size.get("num_spans", 0),
        "session_id": meta.get("mlflow.trace.session", ""),
        "user": meta.get("mlflow.user", ""),
        "claude_code_version": meta.get("mlflow.claude_code_version", ""),
        "prompt": inputs_parsed.get("prompt", ""),
        "response": outputs_parsed.get("response", ""),
    }


def fetch_spans(trace_id, issue_keys):
    """Fetch spans for a trace via the MLflow Python client."""
    client = mlflow.MlflowClient()
    try:
        trace = client.get_trace(trace_id)
    except Exception as e:
        print(f"    WARN: failed to fetch spans for {trace_id}: {e}")
        return []

    docs = []
    for s in trace.data.spans:
        attrs = s.attributes or {}

        start_ns = attrs.get("mlflow.spanStartTimeNs")
        end_ns = s.end_time_ns
        duration_ms = None
        if start_ns and end_ns:
            duration_ms = (end_ns - start_ns) // 1_000_000

        start_iso = None
        if start_ns:
            start_iso = datetime.fromtimestamp(
                start_ns / 1e9, tz=timezone.utc
            ).isoformat()

        inputs_str = json.dumps(s.inputs) if s.inputs else ""
        outputs_str = json.dumps(s.outputs) if s.outputs else ""

        model = attrs.get("mlflow.llm.model", attrs.get("model", ""))

        status_str = ""
        if s.status:
            status_str = str(s.status.status_code.value) if hasattr(s.status, "status_code") else str(s.status)

        error_msg = ""
        if s.status and hasattr(s.status, "description") and s.status.description:
            error_msg = s.status.description

        doc = {
            "trace_id": trace_id,
            "span_id": s.span_id,
            "parent_id": s.parent_id or "",
            "name": s.name,
            "span_type": attrs.get("mlflow.spanType", ""),
            "status": status_str,
            "start_time": start_iso,
            "duration_ms": duration_ms,
            "inputs": inputs_str[:50000],
            "outputs": outputs_str[:50000],
            "tool_name": attrs.get("tool_name", ""),
            "issue_keys": issue_keys,
            "model": model,
            "error": error_msg,
        }
        docs.append(doc)

    return docs


def run_sync(full=False, dry_run=False, mlflow_uri=None, elastic_uri=None):
    global MLFLOW_URI, ELASTIC_URI
    if mlflow_uri:
        MLFLOW_URI = mlflow_uri
    if elastic_uri:
        ELASTIC_URI = elastic_uri

    mlflow.set_tracking_uri(MLFLOW_URI)

    print(f"MLflow:  {MLFLOW_URI}")
    print(f"Elastic: {ELASTIC_URI}")
    print()

    es = Elasticsearch(ELASTIC_URI)
    if not es.ping():
        print("ERROR: Cannot connect to Elasticsearch")
        sys.exit(1)

    if full and not dry_run:
        for idx in [TRACES_INDEX, SPANS_INDEX]:
            if es.indices.exists(index=idx):
                es.indices.delete(index=idx)
                print(f"  Deleted index: {idx}")

    if not dry_run:
        ensure_indices(es)

    since_ms = 0 if full else get_high_water_mark(es)
    if since_ms:
        since_dt = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)
        print(f"Syncing traces newer than {since_dt.isoformat()}")
    else:
        print("Syncing all traces (full)")
    print()

    print("Fetching trace metadata from MLflow...")
    t0 = time.time()
    raw_traces = fetch_traces_from_mlflow(since_ms)
    print(f"  Found {len(raw_traces)} new traces ({time.time() - t0:.1f}s)")
    print()

    if not raw_traces:
        print("Nothing to sync.")
        return

    if dry_run:
        issue_keys_all = set()
        for rt in raw_traces:
            doc = parse_trace(rt)
            issue_keys_all.update(doc["issue_keys"])
        print(f"Dry run summary:")
        print(f"  Traces to index: {len(raw_traces)}")
        print(f"  Unique issue keys: {len(issue_keys_all)}")
        return

    # Index traces
    print("Indexing traces...")
    trace_actions = []
    trace_docs = []
    for rt in raw_traces:
        doc = parse_trace(rt)
        trace_docs.append(doc)
        trace_actions.append({
            "_index": TRACES_INDEX,
            "_id": doc["trace_id"],
            "_source": doc,
        })

    success, errors = bulk(es, trace_actions, raise_on_error=False)
    print(f"  Indexed {success} traces ({len(errors)} errors)")

    # Index spans
    print("Fetching and indexing spans...")
    total_spans = 0
    total_errors = 0
    for i, doc in enumerate(trace_docs):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"  Processing trace {i + 1}/{len(trace_docs)}...")

        spans = fetch_spans(doc["trace_id"], doc["issue_keys"])
        if not spans:
            continue

        span_actions = [
            {
                "_index": SPANS_INDEX,
                "_id": f"{s['trace_id']}_{s['span_id']}",
                "_source": s,
            }
            for s in spans
        ]
        s_ok, s_err = bulk(es, span_actions, raise_on_error=False)
        total_spans += s_ok
        total_errors += len(s_err)

    print()
    print(f"Done. Indexed {success} traces, {total_spans} spans ({total_errors} errors)")

    # Print summary
    es.indices.refresh(index=TRACES_INDEX)
    es.indices.refresh(index=SPANS_INDEX)
    t_count = es.count(index=TRACES_INDEX)["count"]
    s_count = es.count(index=SPANS_INDEX)["count"]
    print(f"Total in Elastic: {t_count} traces, {s_count} spans")


def main():
    parser = argparse.ArgumentParser(
        description="Sync MLflow traces into Elasticsearch"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Reindex all traces (ignores high-water mark)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would be synced without writing",
    )
    parser.add_argument(
        "--mlflow-uri", default=None,
        help=f"MLflow tracking URI (default: {MLFLOW_URI})",
    )
    parser.add_argument(
        "--elastic-uri", default=None,
        help=f"Elasticsearch URI (default: {ELASTIC_URI})",
    )
    args = parser.parse_args()
    run_sync(
        full=args.full,
        dry_run=args.dry_run,
        mlflow_uri=args.mlflow_uri,
        elastic_uri=args.elastic_uri,
    )


if __name__ == "__main__":
    main()
