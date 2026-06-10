#!/usr/bin/env python3
"""Aggregate architecture-context benchmark results.

Reads answer and judgment JSON files produced by bench-answer-* and
bench-judge skills, computes per-mode and per-tier averages, and
writes a summary with cross-mode comparison.

Usage:
    python scripts/aggregate_benchmark.py \
        --results-dir var/benchmarks/arch-context/results \
        --corpus var/benchmarks/arch-context/corpus-AB-final.yaml \
        --arch-context-commit abc123 \
        --agent-model opus \
        --judge-model sonnet
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml


DIMENSIONS = ["accuracy", "grounding", "scope_awareness", "gap_acknowledgment"]
WEIGHTS = {
    "accuracy": 0.4,
    "grounding": 0.2,
    "scope_awareness": 0.2,
    "gap_acknowledgment": 0.2,
}
CONTEXT_MODES = ["flat_files", "arch_query"]
TIERS = [1, 2, 3, 4]


def load_corpus(corpus_path: Path) -> dict:
    with open(corpus_path) as f:
        return yaml.safe_load(f)


def load_json_files(directory: Path) -> list[dict]:
    results = []
    if not directory.exists():
        return results
    for p in sorted(directory.glob("*.json")):
        try:
            with open(p) as f:
                results.append(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: skipping {p}: {e}", file=sys.stderr)
    return results


def question_tier(question_id: str, corpus: dict) -> int | None:
    for q in corpus.get("questions", []):
        if q["id"] == question_id:
            return q["tier"]
    return None


def compute_tier_stats(
    judgments: list[dict], corpus: dict
) -> dict[str, dict]:
    by_tier: dict[int, list[dict]] = defaultdict(list)
    for j in judgments:
        tier = question_tier(j["question_id"], corpus)
        if tier is not None:
            by_tier[tier].append(j)

    tier_stats = {}
    for tier in TIERS:
        items = by_tier.get(tier, [])
        key = f"tier_{tier}"
        if not items:
            tier_stats[key] = {
                "count": 0,
                "composite_avg": 0.0,
                **{f"{d}_avg": 0.0 for d in DIMENSIONS},
                "false_claims_total": 0,
                "missed_gaps_total": 0,
            }
            continue

        count = len(items)
        tier_stats[key] = {
            "count": count,
            "composite_avg": round(
                sum(j["composite_score"] for j in items) / count, 1
            ),
            **{
                f"{d}_avg": round(
                    sum(j["scores"][d] for j in items) / count, 1
                )
                for d in DIMENSIONS
            },
            "false_claims_total": sum(j.get("false_claims", 0) for j in items),
            "missed_gaps_total": sum(j.get("missed_gaps", 0) for j in items),
        }
    return tier_stats


def compute_mode_stats(
    mode: str,
    results_dir: Path,
    corpus: dict,
) -> dict:
    answers = load_json_files(results_dir / "answers" / mode)
    judgments = load_json_files(results_dir / "judgments" / mode)

    tier_stats = compute_tier_stats(judgments, corpus)

    total_judged = len(judgments)
    composite_avg = 0.0
    if total_judged > 0:
        composite_avg = round(
            sum(j["composite_score"] for j in judgments) / total_judged, 1
        )

    return {
        "total_questions": len(corpus.get("questions", [])),
        "total_answered": len(answers),
        "total_judged": total_judged,
        "composite_avg": composite_avg,
        "per_tier": tier_stats,
    }


def compute_comparison(flat_stats: dict, query_stats: dict) -> dict:
    per_tier = {}
    for tier in TIERS:
        key = f"tier_{tier}"
        ft = flat_stats["per_tier"].get(key, {})
        qt = query_stats["per_tier"].get(key, {})

        fc = ft.get("composite_avg", 0.0)
        qc = qt.get("composite_avg", 0.0)
        delta = round(qc - fc, 1)

        dim_deltas = {}
        for d in DIMENSIONS:
            fv = ft.get(f"{d}_avg", 0.0)
            qv = qt.get(f"{d}_avg", 0.0)
            dim_deltas[f"{d}_delta"] = round(qv - fv, 1)

        winner = "tie"
        if abs(delta) >= 0.1:
            winner = "arch_query" if delta > 0 else "flat_files"

        per_tier[key] = {
            "composite_delta": delta,
            **dim_deltas,
            "winner": winner,
        }

    fc_total = flat_stats.get("composite_avg", 0.0)
    qc_total = query_stats.get("composite_avg", 0.0)
    quality_delta = round(qc_total - fc_total, 1)
    quality_winner = "tie"
    if abs(quality_delta) >= 0.1:
        quality_winner = "arch_query" if quality_delta > 0 else "flat_files"

    return {
        "per_tier": per_tier,
        "verdict": {
            "quality_winner": quality_winner,
            "quality_margin": abs(quality_delta),
            "flat_files_composite": fc_total,
            "arch_query_composite": qc_total,
        },
    }


def build_per_question(results_dir: Path, corpus: dict) -> list[dict]:
    rows = []
    for q in corpus.get("questions", []):
        qid = q["id"]
        row = {"question_id": qid, "tier": q["tier"]}
        for mode in CONTEXT_MODES:
            answer_path = results_dir / "answers" / mode / f"{qid}.json"
            judgment_path = results_dir / "judgments" / mode / f"{qid}.json"
            answered = answer_path.exists()
            judged = judgment_path.exists()
            composite = None
            if judged:
                try:
                    with open(judgment_path) as f:
                        j = json.load(f)
                    composite = j.get("composite_score")
                except (json.JSONDecodeError, OSError):
                    pass
            row[mode] = {
                "answered": answered,
                "judged": judged,
                "composite_score": composite,
            }
        rows.append(row)
    return rows


def find_failures(results_dir: Path, corpus: dict) -> list[dict]:
    failures = []
    for q in corpus.get("questions", []):
        qid = q["id"]
        for mode in CONTEXT_MODES:
            answer_path = results_dir / "answers" / mode / f"{qid}.json"
            if not answer_path.exists():
                failures.append({
                    "question_id": qid,
                    "mode": mode,
                    "stage": "answer",
                    "reason": "missing",
                })
                continue
            judgment_path = results_dir / "judgments" / mode / f"{qid}.json"
            if not judgment_path.exists():
                failures.append({
                    "question_id": qid,
                    "mode": mode,
                    "stage": "judgment",
                    "reason": "missing",
                })
    return failures


def main():
    parser = argparse.ArgumentParser(description="Aggregate benchmark results")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--arch-context-commit", default="unknown")
    parser.add_argument("--arch-query-version", default="unknown")
    parser.add_argument("--agent-model", default="unknown")
    parser.add_argument("--judge-model", default="unknown")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    corpus = load_corpus(Path(args.corpus))

    per_mode = {}
    for mode in CONTEXT_MODES:
        per_mode[mode] = compute_mode_stats(mode, results_dir, corpus)

    comparison = compute_comparison(
        per_mode.get("flat_files", {}),
        per_mode.get("arch_query", {}),
    )

    per_question = build_per_question(results_dir, corpus)
    failures = find_failures(results_dir, corpus)

    summary = {
        "arch_context_commit": args.arch_context_commit,
        "arch_query_version": args.arch_query_version,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "corpus_version": corpus.get("version", "unknown"),
        "agent_model": args.agent_model,
        "judge_model": args.judge_model,
        "per_mode": per_mode,
        "comparison": comparison,
        "per_question": per_question,
        "failures": failures,
    }

    json_path = results_dir / "benchmark-summary.json"
    yaml_path = results_dir / "benchmark-summary.yaml"

    results_dir.mkdir(parents=True, exist_ok=True)

    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote {json_path}")

    with open(yaml_path, "w") as f:
        yaml.dump(summary, f, default_flow_style=False, sort_keys=False)
    print(f"Wrote {yaml_path}")

    fc = per_mode.get("flat_files", {}).get("composite_avg", 0)
    qc = per_mode.get("arch_query", {}).get("composite_avg", 0)
    winner = comparison.get("verdict", {}).get("quality_winner", "unknown")
    print(f"\nflat_files composite: {fc}  |  arch_query composite: {qc}  |  winner: {winner}")

    if failures:
        print(f"\n{len(failures)} failures detected (missing answers or judgments)")


if __name__ == "__main__":
    main()
