#!/usr/bin/env python3
"""Carve an exact payload byte range and preserve its provenance in JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--end", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--topic", required=True)
    args = parser.parse_args()

    payload = args.payload.resolve()
    output = args.output.resolve()
    if not payload.is_file() or payload.is_symlink():
        parser.error(f"payload must be a regular, non-symlink file: {payload}")
    size = payload.stat().st_size
    if not 0 <= args.start < args.end <= size:
        parser.error(f"range [{args.start}, {args.end}) is outside payload size {size}")

    with payload.open("rb") as stream:
        stream.seek(args.start)
        content = stream.read(args.end - args.start)
    content_sha = hashlib.sha256(content).hexdigest()

    if output.exists():
        if not output.is_file() or output.is_symlink():
            parser.error(f"existing output is not a regular, non-symlink file: {output}")
        if file_sha256(output) != content_sha:
            parser.error("refusing to overwrite an existing segment with different bytes")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(output)

    metadata = {
        "schema_version": 1,
        "topic": args.topic,
        "payload": {
            "path": str(payload),
            "size": size,
            "sha256": file_sha256(payload),
        },
        "segment": {
            "path": str(output),
            "start": args.start,
            "start_hex": f"0x{args.start:x}",
            "end_exclusive": args.end,
            "end_exclusive_hex": f"0x{args.end:x}",
            "length": len(content),
            "sha256": content_sha,
            "ascii_printable_ratio": sum(
                byte in (9, 10, 13) or 32 <= byte <= 126 for byte in content
            )
            / len(content),
        },
    }
    sidecar = output.with_suffix(output.suffix + ".json")
    sidecar_data = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()
    if sidecar.exists():
        if not sidecar.is_file() or sidecar.is_symlink() or sidecar.read_bytes() != sidecar_data:
            parser.error(f"refusing to overwrite different sidecar: {sidecar}")
    else:
        temporary_sidecar = sidecar.with_name(f".{sidecar.name}.tmp")
        temporary_sidecar.write_bytes(sidecar_data)
        temporary_sidecar.replace(sidecar)
    print(sidecar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
