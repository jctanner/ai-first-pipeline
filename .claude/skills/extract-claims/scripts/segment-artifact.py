#!/usr/bin/env python3
"""Segment Markdown artifacts into stable source units with bounded context."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA_VERSION = 1
SEGMENTER_VERSION = "markdown-v1"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LIST_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+(.+?)\s*$")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`])")
ABBREVIATIONS = {"e.g.", "i.e.", "mr.", "mrs.", "dr.", "vs.", "etc."}
ARTIFACT_TYPE_OVERRIDES = {
    "security_review": {"preceding_units": 2, "following_units": 2},
    "investigation": {"preceding_units": 2, "following_units": 1},
}


@dataclass(frozen=True)
class RawUnit:
    kind: str
    text: str
    line_start: int
    line_end: int
    heading_path: tuple[str, ...]
    list_preamble: str | None = None


@dataclass(frozen=True)
class SourceUnit:
    id: str
    kind: str
    text: str
    source_locator: str
    line_start: int
    line_end: int
    heading_path: list[str]
    preceding_context: list[str]
    following_context: list[str]
    list_preamble: str | None


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _split_sentences(text: str) -> list[str]:
    protected = text
    for abbreviation in ABBREVIATIONS:
        pattern = re.compile(re.escape(abbreviation), re.IGNORECASE)
        protected = pattern.sub(
            lambda match: match.group(0).replace(".", "\N{ONE DOT LEADER}"), protected
        )
    sentences = SENTENCE_BOUNDARY_RE.split(protected)
    restored = []
    for sentence in sentences:
        sentence = sentence.replace("\N{ONE DOT LEADER}", ".")
        sentence = " ".join(sentence.split()).strip()
        if sentence:
            restored.append(sentence)
    return restored


def _flush_paragraph(
    units: list[RawUnit],
    lines: list[str],
    start: int | None,
    end: int,
    headings: list[str],
) -> tuple[list[str], int | None]:
    if not lines or start is None:
        return [], None
    text = " ".join(part.strip() for part in lines).strip()
    for sentence in _split_sentences(text):
        units.append(RawUnit("sentence", sentence, start, end, tuple(headings)))
    return [], None


def parse_markdown(text: str) -> list[RawUnit]:
    units: list[RawUnit] = []
    headings: list[str] = []
    paragraph: list[str] = []
    paragraph_start: int | None = None
    in_fence = False
    last_prose: str | None = None

    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        if FENCE_RE.match(line):
            paragraph, paragraph_start = _flush_paragraph(
                units, paragraph, paragraph_start, number - 1, headings
            )
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading = HEADING_RE.match(line)
        if heading:
            paragraph, paragraph_start = _flush_paragraph(
                units, paragraph, paragraph_start, number - 1, headings
            )
            level = len(heading.group(1))
            headings = headings[: level - 1] + [heading.group(2).strip()]
            last_prose = None
            continue

        list_item = LIST_RE.match(line)
        if list_item:
            paragraph, paragraph_start = _flush_paragraph(
                units, paragraph, paragraph_start, number - 1, headings
            )
            item = " ".join(list_item.group(1).split())
            units.append(
                RawUnit("list_item", item, number, number, tuple(headings), last_prose)
            )
            continue

        if TABLE_RE.match(line):
            paragraph, paragraph_start = _flush_paragraph(
                units, paragraph, paragraph_start, number - 1, headings
            )
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                units.append(
                    RawUnit("table_row", " | ".join(cells), number, number, tuple(headings))
                )
            continue

        if not line.strip():
            if paragraph:
                prose = " ".join(part.strip() for part in paragraph).strip()
                paragraph, paragraph_start = _flush_paragraph(
                    units, paragraph, paragraph_start, number - 1, headings
                )
                last_prose = prose
            continue

        if paragraph_start is None:
            paragraph_start = number
        paragraph.append(line)

    _flush_paragraph(units, paragraph, paragraph_start, len(lines), headings)
    return units


def segment_artifact(
    source_file: str,
    content: str,
    preceding: int = 1,
    following: int = 1,
    artifact_type: str | None = None,
) -> dict:
    override = ARTIFACT_TYPE_OVERRIDES.get(artifact_type or "", {})
    preceding = override.get("preceding_units", preceding)
    following = override.get("following_units", following)
    raw_units = parse_markdown(content)
    config = {
        "segmenter_version": SEGMENTER_VERSION,
        "preceding_units": preceding,
        "following_units": following,
        "artifact_type": artifact_type,
        "artifact_type_override": override,
    }
    config_digest = _digest(json.dumps(config, sort_keys=True).encode())
    source_digest = _digest(content.encode())
    units: list[SourceUnit] = []
    for index, raw in enumerate(raw_units):
        identity = json.dumps(
            {
                "source_file": source_file,
                "source_digest": source_digest,
                "config_digest": config_digest,
                "index": index,
                "kind": raw.kind,
                "text": raw.text,
                "lines": [raw.line_start, raw.line_end],
            },
            sort_keys=True,
        ).encode()
        units.append(
            SourceUnit(
                id=hashlib.sha256(identity).hexdigest()[:24],
                kind=raw.kind,
                text=raw.text,
                source_locator=f"{source_file}:L{raw.line_start}-L{raw.line_end}",
                line_start=raw.line_start,
                line_end=raw.line_end,
                heading_path=list(raw.heading_path),
                preceding_context=[
                    unit.text for unit in raw_units[max(0, index - preceding) : index]
                ],
                following_context=[
                    unit.text for unit in raw_units[index + 1 : index + 1 + following]
                ],
                list_preamble=raw.list_preamble,
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "source_file": source_file,
        "source_digest": source_digest,
        "configuration": config,
        "configuration_digest": config_digest,
        "unit_count": len(units),
        "units": [asdict(unit) for unit in units],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--source-file")
    parser.add_argument("--preceding", type=int, default=1)
    parser.add_argument("--following", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifact-type", choices=[
        "rfe", "strategy", "security_review", "epic", "investigation", "code_generation"
    ])
    args = parser.parse_args()
    if args.preceding < 0 or args.following < 0:
        parser.error("context window sizes must be non-negative")

    result = segment_artifact(
        args.source_file or args.source.as_posix(),
        args.source.read_text(encoding="utf-8"),
        args.preceding,
        args.following,
        args.artifact_type,
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(args.output)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
