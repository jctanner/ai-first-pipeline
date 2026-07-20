#!/usr/bin/env python3
"""Create an offset-preserving printable-string and representation index."""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import sys
from typing import BinaryIO, Iterator


DEFAULT_MIN_LENGTH = 8
DEFAULT_LONG_RUN = 4096
PRINTABLE = bytes([1 if (32 <= i <= 126 or i in (9, 10, 13)) else 0 for i in range(256)])
CLAUDE_ANCHORS = (
    b"installed_plugins.json",
    b"enabledPlugins",
    b"has conflicting manifests",
    b"session-only plugins from --plugin-dir",
    b"Unknown command:",
    b"<command-message>",
    b"slash_commands",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_printable_runs(stream: BinaryIO, minimum: int) -> Iterator[tuple[int, bytes]]:
    offset = 0
    start: int | None = None
    run = bytearray()
    while chunk := stream.read(1024 * 1024):
        for byte in chunk:
            if PRINTABLE[byte]:
                if start is None:
                    start = offset
                run.append(byte)
            else:
                if start is not None and len(run) >= minimum:
                    yield start, bytes(run)
                start = None
                run.clear()
            offset += 1
    if start is not None and len(run) >= minimum:
        yield start, bytes(run)


def escaped_tsv(data: bytes) -> str:
    return (
        data.decode("ascii", errors="backslashreplace")
        .replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def js_likelihood(data: bytes) -> dict[str, object]:
    sample = data[: 1024 * 1024]
    text = sample.decode("ascii", errors="ignore")
    tokens = {
        "function": len(re.findall(r"\bfunction\b", text)),
        "arrow": text.count("=>"),
        "const_let_var": len(re.findall(r"\b(?:const|let|var)\b", text)),
        "braces": text.count("{") + text.count("}"),
        "semicolons": text.count(";"),
        "source_url": text.count("sourceURL"),
    }
    score = sum(min(value, 20) for value in tokens.values())
    return {"candidate": score >= 12, "score": score, "tokens": tokens}


def immutable_write(path: Path, data: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != data:
            raise ValueError(f"refusing to overwrite different output: {path}")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def atomic_json(path: Path, value: object) -> None:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    immutable_write(path, data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--min-length", type=int, default=DEFAULT_MIN_LENGTH)
    parser.add_argument("--long-run", type=int, default=DEFAULT_LONG_RUN)
    args = parser.parse_args()

    payload = args.payload.resolve()
    output_dir = args.output_dir.resolve()
    if not payload.is_file() or payload.is_symlink():
        parser.error(f"payload must be a regular, non-symlink file: {payload}")
    if args.min_length < 1 or args.long_run < args.min_length:
        parser.error("invalid run lengths")
    output_dir.mkdir(parents=True, exist_ok=True)

    strings_path = output_dir / "strings.tsv"
    long_runs: list[dict[str, object]] = []
    counts = {"printable_runs": 0, "long_printable_runs": 0}
    temporary_strings = strings_path.with_name(f".{strings_path.name}.{os.getpid()}.tmp")
    with payload.open("rb") as stream, temporary_strings.open("w", encoding="utf-8") as index:
        index.write("offset_decimal\toffset_hex\tlength\ttext_escaped\n")
        for start, data in iter_printable_runs(stream, args.min_length):
            counts["printable_runs"] += 1
            index.write(f"{start}\t0x{start:x}\t{len(data)}\t{escaped_tsv(data)}\n")
            if len(data) >= args.long_run:
                counts["long_printable_runs"] += 1
                likelihood = js_likelihood(data)
                long_runs.append(
                    {
                        "start": start,
                        "start_hex": f"0x{start:x}",
                        "end_exclusive": start + len(data),
                        "end_exclusive_hex": f"0x{start + len(data):x}",
                        "length": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "javascript": likelihood,
                        "prefix": escaped_tsv(data[:160]),
                        "suffix": escaped_tsv(data[-160:]),
                    }
                )
    if strings_path.exists():
        if not strings_path.is_file() or strings_path.is_symlink():
            parser.error(f"existing string index is not a regular file: {strings_path}")
        if sha256_file(strings_path) != sha256_file(temporary_strings):
            temporary_strings.unlink()
            parser.error(f"refusing to overwrite different string index: {strings_path}")
        temporary_strings.unlink()
    else:
        temporary_strings.replace(strings_path)

    payload_size = payload.stat().st_size
    payload_sha = sha256_file(payload)
    anchor_groups: list[dict[str, object]] = []
    primary_candidates: dict[tuple[int, int], set[str]] = {}
    with payload.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for anchor in CLAUDE_ANCHORS:
            occurrences: list[dict[str, object]] = []
            cursor = 0
            while True:
                hit = data.find(anchor, cursor)
                if hit < 0:
                    break
                containing_run = next(
                    (
                        run
                        for run in long_runs
                        if int(run["start"]) <= hit < int(run["end_exclusive"])
                    ),
                    None,
                )
                if containing_run and bool(containing_run["javascript"]["candidate"]):  # type: ignore[index]
                    classification = "executable-minified-bundle-candidate"
                    run_key = (
                        int(containing_run["start"]),
                        int(containing_run["end_exclusive"]),
                    )
                    primary_candidates.setdefault(run_key, set()).add(anchor.decode("ascii"))
                else:
                    neighborhood = bytes(data[max(0, hit - 64) : hit + len(anchor) + 64])
                    nul_ratio = neighborhood.count(0) / max(1, len(neighborhood))
                    classification = (
                        "serialized-runtime-or-heap-data"
                        if nul_ratio >= 0.15
                        else "unclassified-non-primary-representation"
                    )
                occurrences.append(
                    {
                        "decimal": hit,
                        "hex": f"0x{hit:x}",
                        "classification": classification,
                        "containing_printable_run": (
                            {
                                "start": containing_run["start"],
                                "end_exclusive": containing_run["end_exclusive"],
                                "sha256": containing_run["sha256"],
                            }
                            if containing_run
                            else None
                        ),
                    }
                )
                cursor = hit + 1
            anchor_groups.append(
                {
                    "anchor": anchor.decode("ascii"),
                    "count": len(occurrences),
                    "occurrences": occurrences,
                }
            )
        trailer_start = max(0, payload_size - 65536)
        trailer = bytes(data[trailer_start:])

    atomic_json(
        output_dir / "printable-runs.json",
        {
            "schema_version": 1,
            "payload": {"path": str(payload), "size": payload_size, "sha256": payload_sha},
            "parameters": {"min_length": args.min_length, "long_run": args.long_run},
            "counts": counts,
            "runs": long_runs,
        },
    )
    ranked_primary = sorted(
        primary_candidates.items(), key=lambda item: (-len(item[1]), item[0][0])
    )
    primary_application = None
    if ranked_primary and len(ranked_primary[0][1]) >= 3:
        (primary_start, primary_end), primary_anchors = ranked_primary[0]
        primary_run = next(run for run in long_runs if run["start"] == primary_start)
        primary_application = {
            "start": primary_start,
            "start_hex": f"0x{primary_start:x}",
            "end_exclusive": primary_end,
            "end_exclusive_hex": f"0x{primary_end:x}",
            "length": primary_end - primary_start,
            "sha256": primary_run["sha256"],
            "prefix": primary_run["prefix"],
            "suffix": primary_run["suffix"],
            "distinctive_anchors": sorted(primary_anchors),
            "basis": "One long printable CommonJS run contains at least three distinct Claude-specific anchors in JavaScript syntax.",
        }

    atomic_json(
        output_dir / "representations.json",
        {
            "schema_version": 1,
            "payload": {"path": str(payload), "size": payload_size, "sha256": payload_sha},
            "distinctive_anchor_groups": anchor_groups,
            "long_run_summary": [
                {
                    "start": run["start"],
                    "end_exclusive": run["end_exclusive"],
                    "length": run["length"],
                    "sha256": run["sha256"],
                    "javascript": run["javascript"],
                }
                for run in long_runs
            ],
            "trailer": {
                "start": trailer_start,
                "length": len(trailer),
                "sha256": hashlib.sha256(trailer).hexdigest(),
                "bun_markers": [
                    {"relative_offset": match.start(), "text": match.group().decode("ascii")}
                    for match in re.finditer(rb"(?i)bun[^\x00\r\n]{0,80}", trailer)
                ][:100],
            },
            "primary_application": primary_application,
            "classification_status": (
                "primary-application-representation-identified"
                if primary_application
                else "candidate-index-only"
            ),
            "classification_note": "Occurrences inside the identified CommonJS run are executable-bundle candidates; NUL-rich duplicate records are classified separately and never selected merely because they occur first.",
        },
    )
    print(output_dir / "representations.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
