#!/usr/bin/env python3
"""Create a canonical, intentionally incomplete extraction artifact scaffold."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def create_scaffold(segments: dict, metadata: dict) -> dict:
    run_key = metadata.get("run_key")
    if not run_key:
        identity = json.dumps({
            "source_file": segments["source_file"],
            "artifact_digest": segments.get("source_digest"),
            "extractor_revision": metadata["extractor_revision"],
            "configuration_digest": metadata.get("configuration_digest"),
        }, sort_keys=True, separators=(",", ":")).encode()
        run_key = "sha256:" + hashlib.sha256(identity).hexdigest()
    units = []
    for source_unit in segments.get("units", []):
        units.append({
            "source_unit": source_unit,
            "selection": {
                "classification": "__REQUIRED__",
                "evaluator_revision": metadata["extractor_revision"],
            },
            "ambiguity": {
                "status": "__REQUIRED__",
                "evaluator_revision": metadata["extractor_revision"],
            },
            "claims": [],
        })

    return {
        "run_key": run_key,
        "source_file": segments["source_file"],
        "pipeline_slug": metadata["pipeline_slug"],
        "artifact_type": metadata.get("artifact_type"),
        "artifact_digest": segments.get("source_digest"),
        "extractor_revision": metadata["extractor_revision"],
        "repository_revision": metadata.get("repository_revision"),
        "model": metadata.get("model"),
        "harness": metadata.get("harness"),
        "configuration_digest": metadata.get("configuration_digest"),
        "decontextualization_mode": metadata.get("decontextualization_mode", "basic"),
        "configuration": segments.get("configuration", {}),
        "segmentation_version": metadata.get("segmentation_version"),
        "segmentation_configuration_digest": segments.get("configuration_digest"),
        "preceding_context_units": metadata.get("preceding_context_units"),
        "following_context_units": metadata.get("following_context_units"),
        "units": units,
    }


def _write_atomic(path: Path, data: dict) -> None:
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("segments", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-key")
    parser.add_argument("--pipeline-slug", required=True)
    parser.add_argument("--artifact-type", required=True)
    parser.add_argument("--extractor-revision", required=True)
    parser.add_argument("--repository-revision")
    parser.add_argument("--model")
    parser.add_argument("--harness")
    parser.add_argument("--configuration-digest")
    parser.add_argument(
        "--decontextualization-mode", choices=("basic", "full"), default="basic"
    )
    parser.add_argument("--segmentation-version")
    parser.add_argument("--preceding-context-units", type=int)
    parser.add_argument("--following-context-units", type=int)
    args = parser.parse_args()

    metadata = {
        key: value
        for key, value in vars(args).items()
        if key not in {"segments", "output"}
    }
    scaffold = create_scaffold(
        json.loads(args.segments.read_text(encoding="utf-8")), metadata
    )
    _write_atomic(args.output, scaffold)
    print(f"created scaffold: {len(scaffold['units'])} source units")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
