#!/usr/bin/env python3
"""Match source anchor groups against every representation in a Bun payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
from pathlib import Path
import sys


def find_all(data: mmap.mmap, needle: bytes) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    while True:
        hit = data.find(needle, cursor)
        if hit < 0:
            return offsets
        offsets.append(hit)
        cursor = hit + 1


def containing_primary(offset: int, primary: dict[str, object] | None) -> bool:
    return bool(
        primary
        and int(primary["start"]) <= offset < int(primary["end_exclusive"])
    )


def best_cluster(hits: list[dict[str, object]], max_span: int) -> list[dict[str, object]]:
    ordered = sorted(hits, key=lambda hit: int(hit["offset"]))
    best: list[dict[str, object]] = []
    left = 0
    for right in range(len(ordered)):
        while int(ordered[right]["offset"]) - int(ordered[left]["offset"]) > max_span:
            left += 1
        while left < right and any(
            ordered[index]["anchor"] == ordered[left]["anchor"]
            for index in range(left + 1, right + 1)
        ):
            left += 1
        candidate = ordered[left : right + 1]
        candidate_unique = len({str(hit["anchor"]) for hit in candidate})
        best_unique = len({str(hit["anchor"]) for hit in best})
        candidate_span = (
            int(candidate[-1]["offset"]) - int(candidate[0]["offset"]) if candidate else 0
        )
        best_span = int(best[-1]["offset"]) - int(best[0]["offset"]) if best else sys.maxsize
        if (candidate_unique, -candidate_span, -len(candidate)) > (
            best_unique,
            -best_span,
            -len(best),
        ):
            best = candidate
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path)
    parser.add_argument("source_anchors", type=Path)
    parser.add_argument("representations", type=Path)
    parser.add_argument("hits_output", type=Path)
    parser.add_argument("correspondences_output", type=Path)
    parser.add_argument("--max-span", type=int, default=200_000)
    parser.add_argument("--binary-manifest", type=Path)
    args = parser.parse_args()

    payload = args.payload.resolve()
    catalog = json.loads(args.source_anchors.read_text())
    representations = json.loads(args.representations.read_text())
    primary = representations.get("primary_application")
    expected_sha = representations["payload"]["sha256"]
    digest = hashlib.sha256()
    with payload.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha = digest.hexdigest()
    if actual_sha != expected_sha:
        parser.error(f"payload hash {actual_sha} differs from representation index {expected_sha}")

    binary_sha = None
    if args.binary_manifest:
        binary_sha = json.loads(args.binary_manifest.read_text())["binary"]["sha256"]
    topic_hits: list[dict[str, object]] = []
    correspondences: list[dict[str, object]] = []
    with payload.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for topic in catalog["topics"]:
            hits: list[dict[str, object]] = []
            anchors = []
            for anchor_record in topic["ordered_anchors"]:
                anchor = str(anchor_record["text"])
                offsets = find_all(data, anchor.encode("utf-8"))
                occurrences = [
                    {
                        "offset": offset,
                        "offset_hex": f"0x{offset:x}",
                        "representation": (
                            "primary-application" if containing_primary(offset, primary) else "non-primary"
                        ),
                    }
                    for offset in offsets
                ]
                anchors.append({**anchor_record, "occurrences": occurrences})
                hits.extend({"anchor": anchor, **occurrence} for occurrence in occurrences)
            topic_hits.append({"id": topic["id"], "anchors": anchors})

            primary_hits = [hit for hit in hits if hit["representation"] == "primary-application"]
            cluster = best_cluster(primary_hits, args.max_span)
            unique_anchors = sorted({str(hit["anchor"]) for hit in cluster})
            if cluster:
                start = min(int(hit["offset"]) for hit in cluster)
                end = max(int(hit["offset"]) + len(str(hit["anchor"]).encode()) for hit in cluster)
            else:
                start = end = None
            correspondences.append(
                {
                    "topic": topic["id"],
                    "binary_sha256": binary_sha,
                    "payload_sha256": actual_sha,
                    "payload_offset_start": start,
                    "payload_offset_end_exclusive": end,
                    "anchor_hits": cluster,
                    "distinct_anchor_count": len(unique_anchors),
                    "old_source": topic["old_source"],
                    "mapping_confidence": (
                        "bundle-candidate" if len(unique_anchors) >= 3 else "insufficient-anchors"
                    ),
                    "differences": [],
                }
            )

    hits_result = {
        "schema_version": 1,
        "payload": {"path": str(payload), "sha256": actual_sha, "size": payload.stat().st_size},
        "source": catalog["source"],
        "topics": topic_hits,
    }
    correspondence_result = {
        "schema_version": 1,
        "payload": hits_result["payload"],
        "correspondences": correspondences,
        "note": "bundle-candidate means three co-located primary-representation anchors; control-flow review is still required before bundle-confirmed.",
    }
    for path, value in ((args.hits_output, hits_result), (args.correspondences_output, correspondence_result)):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        if path.exists():
            if not path.is_file() or path.is_symlink() or path.read_bytes() != data:
                parser.error(f"refusing to overwrite different output: {path}")
        else:
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
    print(args.correspondences_output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
