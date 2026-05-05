#!/usr/bin/env python3
"""Build the benchmark corpus from extracted JSONL files.

Reads all raw/*.jsonl files produced by extract_corpus_tier*.py,
normalizes and deduplicates, validates source_files exist in the
architecture-context directory, extracts source_excerpt (max 500 chars),
assigns sequential IDs (t1-001, t2-001...), and writes corpus.yaml.

Usage:
    python scripts/build_corpus.py \
        --raw-dir benchmarks/arch-context/raw \
        --arch-context-dir .context/architecture-context \
        --output benchmarks/arch-context/corpus.yaml

    # Add hand-curated questions from a YAML seed file
    python scripts/build_corpus.py \
        --raw-dir benchmarks/arch-context/raw \
        --arch-context-dir .context/architecture-context \
        --seed benchmarks/arch-context/seed-questions.yaml \
        --output benchmarks/arch-context/corpus.yaml
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml


_OVERLAP_THRESHOLD = 0.65
_MAX_EXCERPT = 500


def load_jsonl_files(raw_dir: Path) -> list[dict]:
    records = []
    for p in sorted(raw_dir.glob("*.jsonl")):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"  Warning: bad JSON in {p}: {e}", file=sys.stderr)
    return records


def load_seed(seed_path: Path) -> list[dict]:
    if not seed_path.exists():
        return []
    with open(seed_path) as f:
        data = yaml.safe_load(f)
    return data.get("questions", []) if isinstance(data, dict) else data or []


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def token_overlap(a: str, b: str) -> float:
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    return len(intersection) / min(len(ta), len(tb))


def deduplicate_questions(records: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for r in records:
        question = r.get("question", "")
        is_dup = False
        for k in kept:
            if r.get("tier") != k.get("tier"):
                continue
            if r.get("component", "") != k.get("component", ""):
                continue
            if token_overlap(question, k.get("question", "")) >= _OVERLAP_THRESHOLD:
                if len(question) > len(k.get("question", "")):
                    kept.remove(k)
                    kept.append(r)
                is_dup = True
                break
        if not is_dup:
            kept.append(r)
    return kept


def find_source_files(
    record: dict, arch_dir: Path
) -> list[str]:
    explicit = record.get("source_files")
    if explicit:
        return [
            sf for sf in explicit
            if (arch_dir / sf).exists()
        ]

    component = record.get("component")
    version = record.get("version")

    if not component:
        return []

    candidates = []
    if version:
        candidates.append(f"architecture/{version}/{component}.md")

    for vdir in sorted(arch_dir.glob("architecture/rhoai-*"), reverse=True):
        if vdir.is_dir():
            rel = f"architecture/{vdir.name}/{component}.md"
            if rel not in candidates:
                candidates.append(rel)

    for c in candidates:
        if (arch_dir / c).exists():
            return [c]

    platform_candidates = []
    for vdir in sorted(arch_dir.glob("architecture/rhoai-*"), reverse=True):
        platform = vdir / "PLATFORM.md"
        if platform.exists():
            platform_candidates.append(f"architecture/{vdir.name}/PLATFORM.md")
            break

    return platform_candidates[:1]


def extract_excerpt(source_file: str, arch_dir: Path, component: str | None) -> str:
    full_path = arch_dir / source_file
    if not full_path.exists():
        return ""

    try:
        content = full_path.read_text(errors="replace")
    except OSError:
        return ""

    if component:
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if component.lower() in line.lower():
                start = max(0, i)
                end = min(len(lines), i + 10)
                excerpt = "\n".join(lines[start:end])
                return excerpt[:_MAX_EXCERPT]

    return content[:_MAX_EXCERPT]


def get_arch_context_commit(arch_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(arch_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except FileNotFoundError:
        return "unknown"


def detect_target_version(arch_dir: Path) -> str:
    arch_path = arch_dir / "architecture"
    if not arch_path.exists():
        return "unknown"
    versions = sorted(
        (d.name for d in arch_path.iterdir() if d.is_dir() and d.name.startswith("rhoai-")),
        reverse=True,
    )
    return versions[0] if versions else "unknown"


def assign_ids(records: list[dict]) -> list[dict]:
    by_tier: dict[int, list[dict]] = defaultdict(list)
    for r in records:
        by_tier[r.get("tier", 0)].append(r)

    result = []
    for tier in sorted(by_tier.keys()):
        for i, r in enumerate(by_tier[tier], start=1):
            r["id"] = f"t{tier}-{i:03d}"
            result.append(r)
    return result


def build_corpus_question(record: dict) -> dict:
    q = {
        "id": record["id"],
        "tier": record["tier"],
        "category": record.get("category", "unknown"),
        "question": record["question"],
        "expected_answer": record.get("expected_answer", "NEEDS_CURATION"),
        "expected_answerable": record.get("expected_answerable", True),
        "source_files": record.get("source_files", []),
        "source_excerpt": record.get("source_excerpt", ""),
    }
    tags = record.get("tags", [])
    if tags:
        q["tags"] = tags
    return q


def main():
    parser = argparse.ArgumentParser(
        description="Build benchmark corpus from extracted questions"
    )
    parser.add_argument(
        "--raw-dir",
        default="benchmarks/arch-context/raw",
        help="Directory containing extracted JSONL files",
    )
    parser.add_argument(
        "--arch-context-dir",
        default=".context/architecture-context",
        help="Path to architecture-context checkout",
    )
    parser.add_argument(
        "--seed",
        default=None,
        help="Optional YAML file with hand-curated questions",
    )
    parser.add_argument(
        "--output",
        default="benchmarks/arch-context/corpus.yaml",
        help="Output corpus YAML path",
    )
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    arch_dir = Path(args.arch_context_dir)
    output_path = Path(args.output)

    print("Loading extracted questions...")
    records = load_jsonl_files(raw_dir)
    print(f"  Loaded {len(records)} raw records from {raw_dir}")

    if args.seed:
        seed_path = Path(args.seed)
        seed_records = load_seed(seed_path)
        print(f"  Loaded {len(seed_records)} seed questions from {seed_path}")
        records.extend(seed_records)

    print("Deduplicating...")
    records = deduplicate_questions(records)
    print(f"  {len(records)} unique questions after dedup")

    if arch_dir.exists():
        print("Resolving source files and excerpts...")
        for r in records:
            if not r.get("source_files"):
                r["source_files"] = find_source_files(r, arch_dir)
            if not r.get("source_excerpt") and r.get("source_files"):
                r["source_excerpt"] = extract_excerpt(
                    r["source_files"][0], arch_dir, r.get("component")
                )
    else:
        print(f"  Warning: {arch_dir} not found, skipping source resolution")

    records = assign_ids(records)

    by_tier = defaultdict(int)
    for r in records:
        by_tier[r["tier"]] += 1

    commit = get_arch_context_commit(arch_dir)
    target_version = detect_target_version(arch_dir)

    corpus = {
        "version": "1.0",
        "architecture_context_commit": commit,
        "generated_date": str(date.today()),
        "target_version": target_version,
        "questions": [build_corpus_question(r) for r in records],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(corpus, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\nWrote {len(records)} questions to {output_path}")
    for tier in sorted(by_tier.keys()):
        print(f"  Tier {tier}: {by_tier[tier]} questions")

    needs_curation = sum(
        1 for r in records
        if r.get("expected_answer") == "NEEDS_CURATION"
    )
    if needs_curation:
        print(f"\n  {needs_curation} questions need manual curation (expected_answer=NEEDS_CURATION)")
        print("  Edit the corpus YAML to fill in ground-truth answers before running benchmarks.")


if __name__ == "__main__":
    main()
