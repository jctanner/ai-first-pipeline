#!/usr/bin/env python3
"""Dump skill-related content from API body request files."""

import json
import glob
import os
import sys

base = sys.argv[1] if len(sys.argv) > 1 else "/artifacts/apibodies"
job_name = sys.argv[2] if len(sys.argv) > 2 else ""

if job_name:
    base = os.path.join(base, job_name)

for f in sorted(glob.glob(os.path.join(base, "*.request.json")))[:1]:
    print(f"=== {os.path.basename(f)} ===")
    with open(f) as fh:
        d = json.load(fh)

    # System prompt
    sys_content = d.get("system", "")
    if isinstance(sys_content, list):
        for i, block in enumerate(sys_content):
            text = block.get("text", "") if isinstance(block, dict) else str(block)
            # Print blocks mentioning skills/plugins/unit-convert
            if any(kw in text.lower() for kw in ["unit-convert", "plugin", "skill", "imperial", "metric"]):
                print(f"\n--- system block {i} (len={len(text)}) ---")
                print(text[:4000])
                if len(text) > 4000:
                    print(f"... ({len(text)} total chars)")
    elif isinstance(sys_content, str) and sys_content:
        if any(kw in sys_content.lower() for kw in ["unit-convert", "plugin", "skill"]):
            print(f"\n--- system (len={len(sys_content)}) ---")
            print(sys_content[:4000])

    # User messages
    for m in d.get("messages", []):
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, str):
            print(f"\n--- {role} ---")
            print(content[:2000])
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block["text"]
                    print(f"\n--- {role} ---")
                    print(text[:2000])
