#!/usr/bin/env python3
"""Local benchmark runner for architecture-context A/B testing.

Runs bench-answer and bench-judge skills locally via the Claude Agent
SDK, without requiring K8s or Markov.

Usage:
    # Both modes, all tiers
    python scripts/run_benchmark.py \
        --corpus benchmarks/arch-context/corpus-AB-final.yaml \
        --arch-context-dir .context/architecture-context \
        --arch-query-bin bin/arch-query \
        --output-dir benchmarks/arch-context/results/$(date +%Y%m%d)

    # Single mode, single tier
    python scripts/run_benchmark.py \
        --corpus benchmarks/arch-context/corpus-AB-final.yaml \
        --arch-context-dir .context/architecture-context \
        --arch-query-bin bin/arch-query \
        --mode flat_files \
        --tier 1 \
        --concurrency 3

    # Skip answer phase (re-judge existing answers)
    python scripts/run_benchmark.py \
        --corpus benchmarks/arch-context/corpus-AB-final.yaml \
        --output-dir benchmarks/arch-context/results/20260505 \
        --judge-only
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.agent_runner import run_agent
from lib.prompts import extract_skill_prompt


CONTEXT_MODES = ["flat_files", "arch_query"]


def load_corpus(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def filter_questions(corpus: dict, tier: int | None) -> list[dict]:
    questions = corpus.get("questions", [])
    if tier is not None:
        questions = [q for q in questions if q["tier"] == tier]
    return questions


def build_answer_prompt(
    skill_md: str,
    question: dict,
    mode: str,
    arch_context_dir: str,
    arch_query_bin: str,
    arch_query_base_dir: str,
    output_dir: str,
) -> str:
    parts = [skill_md, "\n\n## Inputs\n"]
    parts.append(f"- QUESTION: {question['question']}\n")
    parts.append(f"- QUESTION_ID: {question['id']}\n")
    parts.append(f"- OUTPUT_DIR: {output_dir}\n")

    if mode == "flat_files":
        parts.append(f"- ARCH_CONTEXT_DIR: {arch_context_dir}\n")
    else:
        full_bin = f"{arch_query_bin} --base-dir {arch_query_base_dir}"
        parts.append(f"- ARCH_QUERY_BIN: {full_bin}\n")

    return "".join(parts)


def build_judge_prompt(
    skill_md: str,
    question: dict,
    answer_path: str,
    output_dir: str,
) -> str:
    parts = [skill_md, "\n\n## Inputs\n"]
    parts.append(f"- QUESTION: {question['question']}\n")
    parts.append(f"- AGENT_ANSWER_PATH: {answer_path}\n")
    parts.append(f"- EXPECTED_ANSWER: {question['expected_answer']}\n")
    parts.append(f"- EXPECTED_ANSWERABLE: {question['expected_answerable']}\n")
    parts.append(f"- SOURCE_EXCERPT: {question.get('source_excerpt', '')}\n")
    parts.append(f"- OUTPUT_DIR: {output_dir}\n")
    return "".join(parts)


async def run_answer(
    question: dict,
    mode: str,
    skill_md: str,
    args: argparse.Namespace,
    semaphore: asyncio.Semaphore,
    output_dir: Path,
    log_dir: Path,
) -> dict:
    qid = question["id"]
    result_path = output_dir / f"{qid}.json"

    if result_path.exists() and not args.force:
        print(f"  [{mode}] {qid}: answer exists, skipping")
        return {"question_id": qid, "mode": mode, "status": "cached"}

    allowed_tools = (
        ["Read", "Write", "Glob", "Grep"]
        if mode == "flat_files"
        else ["Bash", "Write"]
    )

    arch_query_base = str(Path(args.arch_context_dir) / "architecture")

    prompt = build_answer_prompt(
        skill_md=skill_md,
        question=question,
        mode=mode,
        arch_context_dir=args.arch_context_dir,
        arch_query_bin=args.arch_query_bin,
        arch_query_base_dir=arch_query_base,
        output_dir=str(output_dir),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    async with semaphore:
        print(f"  [{mode}] {qid}: answering...")
        result = await run_agent(
            name=f"bench-answer-{mode}-{qid}",
            cwd=str(Path.cwd()),
            prompt=prompt,
            log_dir=log_dir,
            model=args.model,
            allowed_tools=allowed_tools,
        )
        status = "ok" if result.get("success") else "error"
        print(f"  [{mode}] {qid}: {status}")
        return {"question_id": qid, "mode": mode, "status": status}


async def run_judge(
    question: dict,
    mode: str,
    skill_md: str,
    args: argparse.Namespace,
    semaphore: asyncio.Semaphore,
    results_dir: Path,
    log_dir: Path,
) -> dict:
    qid = question["id"]
    answer_path = results_dir / "answers" / mode / f"{qid}.json"
    judgment_dir = results_dir / "judgments" / mode
    judgment_path = judgment_dir / f"{qid}.json"

    if judgment_path.exists() and not args.force:
        print(f"  [{mode}] {qid}: judgment exists, skipping")
        return {"question_id": qid, "mode": mode, "status": "cached"}

    if not answer_path.exists():
        print(f"  [{mode}] {qid}: no answer, skipping judge")
        return {"question_id": qid, "mode": mode, "status": "no_answer"}

    prompt = build_judge_prompt(
        skill_md=skill_md,
        question=question,
        answer_path=str(answer_path),
        output_dir=str(judgment_dir),
    )

    judgment_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    async with semaphore:
        print(f"  [{mode}] {qid}: judging...")
        result = await run_agent(
            name=f"bench-judge-{mode}-{qid}",
            cwd=str(Path.cwd()),
            prompt=prompt,
            log_dir=log_dir,
            model=args.judge_model,
            allowed_tools=["Read", "Write"],
        )
        status = "ok" if result.get("success") else "error"
        print(f"  [{mode}] {qid}: judge {status}")
        return {"question_id": qid, "mode": mode, "status": status}


async def run_mode(
    mode: str,
    questions: list[dict],
    args: argparse.Namespace,
    results_dir: Path,
    log_dir: Path,
):
    print(f"\n{'=' * 60}")
    print(f"Mode: {mode} ({len(questions)} questions)")
    print(f"{'=' * 60}")

    semaphore = asyncio.Semaphore(args.concurrency)
    answer_dir = results_dir / "answers" / mode

    skill_name = f"bench-answer-{'flat' if mode == 'flat_files' else 'query'}"
    skill_path = Path(".claude/skills") / skill_name / "SKILL.md"
    if not skill_path.exists():
        print(f"ERROR: skill not found at {skill_path}", file=sys.stderr)
        return
    answer_skill_md = skill_path.read_text()

    answer_tasks = [
        run_answer(q, mode, answer_skill_md, args, semaphore, answer_dir, log_dir)
        for q in questions
    ]
    answer_results = await asyncio.gather(*answer_tasks)

    answered = sum(1 for r in answer_results if r["status"] in ("ok", "cached"))
    print(f"\n{mode} answers: {answered}/{len(questions)} complete")

    if args.skip_judge:
        return

    judge_skill_path = Path(".claude/skills/bench-judge/SKILL.md")
    if not judge_skill_path.exists():
        print(f"ERROR: judge skill not found at {judge_skill_path}", file=sys.stderr)
        return
    judge_skill_md = judge_skill_path.read_text()

    judge_tasks = [
        run_judge(q, mode, judge_skill_md, args, semaphore, results_dir, log_dir)
        for q in questions
    ]
    judge_results = await asyncio.gather(*judge_tasks)

    judged = sum(1 for r in judge_results if r["status"] in ("ok", "cached"))
    print(f"{mode} judgments: {judged}/{len(questions)} complete")


async def async_main(args: argparse.Namespace):
    corpus = load_corpus(Path(args.corpus))
    questions = filter_questions(corpus, args.tier)

    if not questions:
        print("No questions match the filter criteria", file=sys.stderr)
        sys.exit(1)

    results_dir = Path(args.output_dir)
    log_dir = results_dir / "logs"

    modes = [args.mode] if args.mode else CONTEXT_MODES

    if not args.judge_only:
        for mode in modes:
            await run_mode(mode, questions, args, results_dir, log_dir)
    else:
        print("Judge-only mode: skipping answer phase")
        judge_skill_path = Path(".claude/skills/bench-judge/SKILL.md")
        judge_skill_md = judge_skill_path.read_text()
        semaphore = asyncio.Semaphore(args.concurrency)
        for mode in modes:
            print(f"\nJudging {mode}...")
            tasks = [
                run_judge(
                    q, mode, judge_skill_md, args, semaphore, results_dir, log_dir
                )
                for q in questions
            ]
            await asyncio.gather(*tasks)

    print(f"\n{'=' * 60}")
    print("Running aggregation...")
    print(f"{'=' * 60}")

    from scripts.aggregate_benchmark import main as aggregate_main
    sys.argv = [
        "aggregate_benchmark.py",
        "--results-dir", str(results_dir),
        "--corpus", args.corpus,
        "--agent-model", args.model,
        "--judge-model", args.judge_model,
    ]
    aggregate_main()


def main():
    parser = argparse.ArgumentParser(
        description="Run architecture-context A/B benchmark locally"
    )
    parser.add_argument("--corpus", required=True, help="Path to corpus.yaml")
    parser.add_argument(
        "--arch-context-dir",
        default=".context/architecture-context",
        help="Path to architecture-context directory",
    )
    parser.add_argument(
        "--arch-query-bin",
        default="arch-query",
        help="Path to arch-query binary",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmarks/arch-context/results",
        help="Output directory for results",
    )
    parser.add_argument("--model", default="opus", help="Answer agent model")
    parser.add_argument(
        "--judge-model", default="sonnet", help="Judge agent model"
    )
    parser.add_argument("--mode", choices=CONTEXT_MODES, help="Run single mode")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4], help="Run single tier")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--force", action="store_true", help="Regenerate existing outputs")
    parser.add_argument("--judge-only", action="store_true", help="Skip answer phase")
    parser.add_argument("--skip-judge", action="store_true", help="Skip judge phase")
    args = parser.parse_args()

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
