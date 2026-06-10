#!/usr/bin/env python3
"""Log architecture-context benchmark results to MLflow.

Creates one MLflow experiment with two paired runs (one per context_mode).
Each run logs per-tier and per-dimension metrics, shared params, and the
benchmark summary as an artifact.

Usage:
    python scripts/log_benchmark_to_mlflow.py \
        --results-dir var/benchmarks/arch-context/results \
        --experiment arch-context-access-benchmark \
        --arch-context-commit abc123 \
        --arch-query-version def456

Environment:
    MLFLOW_TRACKING_URI  — required (e.g., http://mlflow:5000)
"""

import argparse
import json
import os
import sys
from pathlib import Path

import mlflow
import yaml


def load_summary(results_dir: Path) -> dict:
    json_path = results_dir / "benchmark-summary.json"
    if json_path.exists():
        with open(json_path) as f:
            return json.load(f)

    yaml_path = results_dir / "benchmark-summary.yaml"
    if yaml_path.exists():
        with open(yaml_path) as f:
            return yaml.safe_load(f)

    print(f"ERROR: No benchmark-summary found in {results_dir}", file=sys.stderr)
    sys.exit(1)


def log_mode_run(
    mode: str,
    summary: dict,
    args: argparse.Namespace,
):
    mode_stats = summary.get("per_mode", {}).get(mode)
    if not mode_stats:
        print(f"  Skipping {mode}: no data in summary")
        return

    commit_short = args.arch_context_commit[:8]
    run_date = summary.get("run_date", "unknown")[:10]
    run_name = f"{mode}-{commit_short}-{run_date}"

    with mlflow.start_run(run_name=run_name) as run:
        mlflow.log_params({
            "context_mode": mode,
            "corpus_version": summary.get("corpus_version", "unknown"),
            "arch_context_commit": args.arch_context_commit,
            "agent_model": summary.get("agent_model", "unknown"),
            "judge_model": summary.get("judge_model", "unknown"),
            "arch_query_version": (
                args.arch_query_version if mode == "arch_query" else "n/a"
            ),
        })

        metrics = {
            "composite_avg": mode_stats.get("composite_avg", 0),
            "total_questions": mode_stats.get("total_questions", 0),
            "total_answered": mode_stats.get("total_answered", 0),
            "total_judged": mode_stats.get("total_judged", 0),
        }

        per_tier = mode_stats.get("per_tier", {})
        dimensions = [
            "accuracy", "grounding", "scope_awareness", "gap_acknowledgment",
        ]
        for tier_key, tier_data in per_tier.items():
            tier_num = tier_key.replace("tier_", "")
            metrics[f"tier{tier_num}_composite_avg"] = tier_data.get(
                "composite_avg", 0
            )
            metrics[f"tier{tier_num}_count"] = tier_data.get("count", 0)
            metrics[f"tier{tier_num}_false_claims"] = tier_data.get(
                "false_claims_total", 0
            )
            metrics[f"tier{tier_num}_missed_gaps"] = tier_data.get(
                "missed_gaps_total", 0
            )
            for dim in dimensions:
                val = tier_data.get(f"{dim}_avg", 0)
                metrics[f"tier{tier_num}_{dim}_avg"] = val

        behavior = mode_stats.get("behavior", {})
        for bk, bv in behavior.items():
            if isinstance(bv, (int, float)):
                metrics[f"behavior_{bk}"] = bv

        mlflow.log_metrics(metrics)

        summary_path = Path(args.results_dir) / "benchmark-summary.json"
        if summary_path.exists():
            mlflow.log_artifact(str(summary_path))

        comparison = summary.get("comparison", {})
        verdict = comparison.get("verdict", {})
        if verdict:
            mlflow.set_tags({
                "quality_winner": verdict.get("quality_winner", "unknown"),
                "quality_margin": str(verdict.get("quality_margin", 0)),
            })

        print(f"  Logged run: {run_name} (ID: {run.info.run_id})")


def main():
    parser = argparse.ArgumentParser(
        description="Log benchmark results to MLflow"
    )
    parser.add_argument("--results-dir", required=True)
    parser.add_argument(
        "--experiment",
        default="arch-context-access-benchmark",
    )
    parser.add_argument("--arch-context-commit", default="unknown")
    parser.add_argument("--arch-query-version", default="unknown")
    args = parser.parse_args()

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        print(
            "ERROR: MLFLOW_TRACKING_URI not set",
            file=sys.stderr,
        )
        sys.exit(1)

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(args.experiment)
    print(f"MLflow experiment: {args.experiment}")
    print(f"Tracking URI: {tracking_uri}")

    summary = load_summary(Path(args.results_dir))

    for mode in ["flat_files", "arch_query"]:
        log_mode_run(mode, summary, args)

    print("\nDone.")


if __name__ == "__main__":
    main()
