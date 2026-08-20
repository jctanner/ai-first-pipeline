#!/usr/bin/env python3
"""Scrape skill-disambiguation trial results from markov run logs + kubectl."""

import json
import os
import re
import subprocess
import sys

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "markov-run-a481f69d"
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
MARKOVD_CLI = "checkouts/markovd/bin/markovd-cli"

CATEGORIES = [
    "unambiguous",
    "ambiguous-unqualified",
    "qualified-metric",
    "qualified-imperial",
    "unambiguous-metric-first",
    "ambiguous-metric-first",
    "unambiguous-no-plugin-dir",
    "ambiguous-no-plugin-dir",
    "unambiguous-no-plugin-dir-metric-first",
    "ambiguous-no-plugin-dir-metric-first",
    "unambiguous-swap-enabled-order",
    "unambiguous-swap-installed-order",
]

os.makedirs(RESULTS_DIR, exist_ok=True)

# 1. Parse markov logs to map step paths -> job names
print("Parsing markov run logs...")
logs = subprocess.check_output(
    [MARKOVD_CLI, "runs", "logs", RUN_ID], text=True, stderr=subprocess.STDOUT
)

# Pattern: [run:...-run_categories-{cat}-run_prompts-{prompt}-run_trial-{trial}]
#   registered "submitted_job": map[body:map[job_name:XXXX ...]]
job_map = {}  # (cat, prompt, trial) -> job_name
pat = re.compile(
    r"run_categories-(\d+)-run_prompts-(\d+)-run_trial-(\d+)\]"
    r'.*registered "submitted_job":.*job_name:(\S+)\s'
)
for line in logs.splitlines():
    m = pat.search(line)
    if m:
        cat, prompt, trial, job_name = int(m[1]), int(m[2]), int(m[3]), m[4]
        job_map[(cat, prompt, trial)] = job_name

print(f"Found {len(job_map)} trial jobs")

# 2. Scrape each job's logs
results = []
for (cat, prompt_idx, trial), job_name in sorted(job_map.items()):
    try:
        pod_logs = subprocess.check_output(
            ["kubectl", "logs", "-n", "ai-pipeline", f"job/{job_name}", "-c", "agent"],
            text=True, stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        print(f"  WARN: failed to get logs for {job_name}: {e}")
        continue

    # Extract prompt from "Executing:" line
    exec_match = re.search(r'Executing:.*--print.*"(.+)"', pod_logs)
    prompt_text = exec_match.group(1) if exec_match else ""

    # Extract Claude response (everything between 💬 Claude and the TOKENS/RESET line)
    response_match = re.search(r"💬 Claude (.*?)(?:\x1b\[0m|\[0m)", pod_logs, re.DOTALL)
    response_text = response_match.group(1).strip() if response_match else ""

    # Try to parse as JSON (strip markdown fences)
    response_json = None
    json_text = response_text
    if json_text.startswith("```json"):
        json_text = json_text[7:]
    if json_text.startswith("```"):
        json_text = json_text[3:]
    if json_text.endswith("```"):
        json_text = json_text[:-3]
    json_text = json_text.strip()
    try:
        response_json = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Extract token counts
    tokens_match = re.search(r"TOKENS in=(\d+) out=(\d+) cache_r=(\d+) cache_w=(\d+) total=(\d+)", pod_logs)
    tokens = {}
    if tokens_match:
        tokens = {
            "input": int(tokens_match[1]),
            "output": int(tokens_match[2]),
            "cache_read": int(tokens_match[3]),
            "cache_write": int(tokens_match[4]),
            "total": int(tokens_match[5]),
        }

    record = {
        "run_id": RUN_ID,
        "job_name": job_name,
        "category": CATEGORIES[cat],
        "category_index": cat,
        "prompt_index": prompt_idx,
        "trial": trial,
        "prompt": prompt_text,
        "response_raw": response_text,
        "response_json": response_json,
        "tokens": tokens,
        "plugin_used": response_json.get("plugin", "") if response_json else "",
    }
    results.append(record)
    sys.stdout.write(f"\r  Scraped {len(results)}/{len(job_map)} trials")
    sys.stdout.flush()

print()

# 3. Write results
out_path = os.path.join(RESULTS_DIR, f"{RUN_ID}.json")
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"Wrote {len(results)} results to {out_path}")

# 4. Quick summary
print("\n=== Summary ===")
for cat_name in CATEGORIES:
    cat_results = [r for r in results if r["category"] == cat_name]
    if not cat_results:
        continue
    plugins = {}
    errors = 0
    for r in cat_results:
        p = r.get("plugin_used", "")
        if p:
            plugins[p] = plugins.get(p, 0) + 1
        else:
            errors += 1
    parts = [f"{k}: {v}" for k, v in sorted(plugins.items())]
    if errors:
        parts.append(f"errors: {errors}")
    print(f"  {cat_name}: {', '.join(parts)}")
