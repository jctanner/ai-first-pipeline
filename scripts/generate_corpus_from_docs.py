#!/usr/bin/env python3
"""Generate benchmark corpus directly from architecture-context docs.

Reads the component markdown files and produces well-formed questions
with ground-truth answers across all 4 tiers. This is the filesystem-
based complement to the ES extraction scripts — it generates questions
from what the docs actually contain rather than from agent trace data.

Usage:
    python scripts/generate_corpus_from_docs.py \
        --arch-context-dir deploy/repos/architecture-context \
        --output benchmarks/arch-context/corpus-claude.yaml \
        --version rhoai.next
"""

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml


EXCLUDED_FILES = {"PLATFORM", "README", "RHOAI-Build-Config", "EXTRACTION-REPORT"}
KNOWN_NON_RHOAI = [
    ("InstructLab", "RHEL AI component, not shipped in RHOAI"),
    ("RHAIIS", "separate product (RHEL AI Inference Service), not part of RHOAI"),
    ("Open Data Hub", "upstream community project; RHOAI is the downstream product"),
    ("TensorFlow Serving", "upstream project, not shipped as a standalone RHOAI component"),
    ("Seldon Core", "upstream project, not shipped in RHOAI"),
    ("BentoML", "upstream project, not shipped in RHOAI"),
    ("Kubeflow Pipelines v1", "replaced by Data Science Pipelines (Argo-based) in RHOAI"),
]

_ARCH_QUERY_MAP = {
    "port": "ports {comp}",
    "crd": "crds {comp}",
    "dependency": "deps {comp}",
    "purpose": "component {comp}",
    "repository": "component {comp}",
    "deployment": "component {comp}",
}


def get_components(arch_dir: Path, version: str) -> list[str]:
    vdir = arch_dir / "architecture" / version
    components = []
    for f in sorted(vdir.glob("*.md")):
        name = f.stem
        if name not in EXCLUDED_FILES:
            components.append(name)
    return components


def read_doc(arch_dir: Path, version: str, component: str) -> str:
    path = arch_dir / "architecture" / version / f"{component}.md"
    return path.read_text(errors="replace") if path.exists() else ""


def extract_section(doc: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(doc)
    if not match:
        return ""
    start = match.end()
    next_h2 = re.search(r"^## ", doc[start:], re.MULTILINE)
    end = start + next_h2.start() if next_h2 else len(doc)
    return doc[start:end].strip()


def extract_metadata_field(doc: str, field: str) -> str:
    pattern = re.compile(rf"^\s*-\s*\*\*{re.escape(field)}\*\*:\s*(.+)$", re.MULTILINE)
    match = pattern.search(doc)
    return match.group(1).strip() if match else ""


def extract_crds(doc: str) -> list[dict]:
    crds = []
    section = extract_section(doc, "APIs Exposed")
    for m in re.finditer(
        r"\|\s*([a-z][a-z0-9.-]+)\s*\|\s*(v\w+)\s*\|\s*(\w+)\s*\|\s*(Namespaced|Cluster)\s*\|",
        section,
    ):
        crds.append({
            "group": m.group(1),
            "version": m.group(2),
            "kind": m.group(3),
            "scope": m.group(4),
        })
    return crds


def extract_ports(doc: str) -> list[str]:
    ports = set()
    for m in re.finditer(r"(\d{4,5})/TCP", doc):
        ports.add(m.group(1))
    return sorted(ports)


def extract_purpose_short(doc: str) -> str:
    section = extract_section(doc, "Purpose")
    match = re.search(r"\*\*Short\*\*:\s*(.+?)(?:\n|$)", section)
    return match.group(1).strip() if match else ""


def extract_dependencies(doc: str) -> list[str]:
    section = extract_section(doc, "Dependencies")
    deps = []
    _DEP_SKIP = {
        "Component", "Interaction Type", "Version", "Required", "Purpose",
        "Yes", "No", "Optional", "---",
    }
    for line in section.split("\n"):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c and c != "---" and not set(c) <= {"-"}]
        if cells and cells[0] not in _DEP_SKIP:
            deps.append(cells[0])
    return list(dict.fromkeys(deps))


def get_all_directories(arch_dir: Path) -> list[str]:
    """Return all architecture directories including rhoai.next, excluding symlinks."""
    arch_path = arch_dir / "architecture"
    dirs = []
    for d in sorted(arch_path.iterdir()):
        if d.is_dir() and not d.is_symlink():
            dirs.append(d.name)
    return dirs


def get_symlinks(arch_dir: Path) -> dict[str, str]:
    arch_path = arch_dir / "architecture"
    links = {}
    for item in sorted(arch_path.iterdir()):
        if item.is_symlink():
            links[item.name] = str(item.readlink())
    return links


def get_overlays(arch_dir: Path) -> list[dict]:
    overlay_dir = arch_dir / "overlays"
    if not overlay_dir.exists():
        return []
    overlays = []
    for f in sorted(overlay_dir.glob("*.md")):
        if f.name == "README.md":
            continue
        content = f.read_text(errors="replace")
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else f.stem
        overlays.append({"file": f.name, "title": title})
    return overlays


def excerpt(doc: str, search_term: str, max_len: int = 400) -> str:
    lines = doc.split("\n")
    for i, line in enumerate(lines):
        if search_term.lower() in line.lower():
            start = max(0, i)
            end = min(len(lines), i + 8)
            return "\n".join(lines[start:end])[:max_len]
    return doc[:max_len]


def generate_tier1(components: list[str], arch_dir: Path, version: str) -> list[dict]:
    questions = []

    for comp in components:
        questions.append({
            "tier": 1,
            "category": "inventory-lookup",
            "question": f"Is {comp} documented in the architecture context?",
            "expected_answer": (
                f"Yes. {comp} has a component document at "
                f"architecture/{version}/{comp}.md."
            ),
            "expected_answerable": True,
            "source_files": [f"architecture/{version}/{comp}.md"],
            "source_excerpt": extract_purpose_short(
                read_doc(arch_dir, version, comp)
            )[:400],
            "expected_arch_query_commands": [f"arch-query exists {comp}"],
            "tags": ["positive", "inventory"],
        })

    for name, reason in KNOWN_NON_RHOAI:
        questions.append({
            "tier": 1,
            "category": "inventory-lookup",
            "question": f"Is {name} a RHOAI component?",
            "expected_answer": f"No. {name} is not a RHOAI component — {reason}.",
            "expected_answerable": True,
            "source_files": [f"architecture/{version}/PLATFORM.md"],
            "source_excerpt": f"{name} is not listed in the RHOAI component inventory.",
            "expected_arch_query_commands": [
                f"arch-query exists {name.lower().replace(' ', '-')}",
                f"arch-query search {name.split()[0].lower()}",
            ],
            "tags": ["negative", "product-scope"],
        })

    return questions


def generate_tier2(components: list[str], arch_dir: Path, version: str) -> list[dict]:
    questions = []

    for comp in components:
        doc = read_doc(arch_dir, version, comp)
        if not doc:
            continue

        ports = extract_ports(doc)
        if ports:
            port_list = ", ".join(ports)
            questions.append({
                "tier": 2,
                "category": "fact-extraction",
                "question": f"What ports does {comp} use?",
                "expected_answer": f"{comp} uses ports: {port_list}.",
                "expected_answerable": True,
                "source_files": [f"architecture/{version}/{comp}.md"],
                "source_excerpt": excerpt(doc, "TCP"),
                "expected_arch_query_commands": [f"arch-query ports {comp}"],
                "tags": ["port"],
            })

        crds = extract_crds(doc)
        if crds:
            crd_list = ", ".join(f"{c['kind']} ({c['group']})" for c in crds[:5])
            more = f" and {len(crds) - 5} more" if len(crds) > 5 else ""
            questions.append({
                "tier": 2,
                "category": "fact-extraction",
                "question": f"What CRDs does {comp} manage?",
                "expected_answer": f"{comp} manages: {crd_list}{more}.",
                "expected_answerable": True,
                "source_files": [f"architecture/{version}/{comp}.md"],
                "source_excerpt": excerpt(doc, "CRD"),
                "expected_arch_query_commands": [f"arch-query crds {comp}"],
                "tags": ["crd"],
            })

        deps = extract_dependencies(doc)
        if deps:
            dep_list = ", ".join(deps[:8])
            more = f" and {len(deps) - 8} more" if len(deps) > 8 else ""
            questions.append({
                "tier": 2,
                "category": "fact-extraction",
                "question": f"What are the dependencies of {comp}?",
                "expected_answer": f"{comp} depends on: {dep_list}{more}.",
                "expected_answerable": True,
                "source_files": [f"architecture/{version}/{comp}.md"],
                "source_excerpt": excerpt(doc, "Dependencies"),
                "expected_arch_query_commands": [f"arch-query deps {comp}"],
                "tags": ["dependency"],
            })

        purpose = extract_purpose_short(doc)
        if purpose:
            questions.append({
                "tier": 2,
                "category": "fact-extraction",
                "question": f"What is the purpose of {comp}?",
                "expected_answer": purpose,
                "expected_answerable": True,
                "source_files": [f"architecture/{version}/{comp}.md"],
                "source_excerpt": purpose[:400],
                "expected_arch_query_commands": [f"arch-query component {comp}"],
                "tags": ["purpose"],
            })

    return questions


def generate_tier3(components: list[str], arch_dir: Path, version: str) -> list[dict]:
    questions = []
    component_deps: dict[str, list[str]] = {}

    for comp in components:
        doc = read_doc(arch_dir, version, comp)
        section = extract_section(doc, "Dependencies")
        internal_section = ""
        if "### Internal" in section:
            internal_section = section[section.index("### Internal"):]
        elif "### ODH" in section:
            internal_section = section[section.index("### ODH"):]

        internal_deps = []
        for m in re.finditer(r"\|\s*([A-Za-z][A-Za-z0-9_ /-]+?)\s*\|", internal_section):
            name = m.group(1).strip()
            if name not in ("Component", "Interaction Type", "---", "Purpose"):
                internal_deps.append(name)
        component_deps[comp] = list(dict.fromkeys(internal_deps))

    seen_pairs = set()
    for comp, deps in component_deps.items():
        for dep in deps:
            dep_key = dep.lower().replace(" ", "-").split("/")[0].strip()
            matching = [c for c in components if dep_key in c.lower() or c.lower() in dep_key]
            if not matching:
                continue
            other = matching[0]
            if other == comp:
                continue
            pair = tuple(sorted([comp, other]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            doc_comp = read_doc(arch_dir, version, comp)
            integration_comp = extract_section(doc_comp, "Integration Points")

            purpose_text = None
            for line in integration_comp.split("\n"):
                if not line.strip().startswith("|"):
                    continue
                cells = [c.strip() for c in line.split("|")]
                cells = [c for c in cells if c]
                if not cells or set(cells[0]) <= {"-"}:
                    continue
                partner = cells[0]
                if other.lower() in partner.lower() or partner.lower() in other.lower():
                    purpose_text = cells[-1] if len(cells) >= 2 else None
                    break

            if purpose_text and purpose_text not in ("Purpose", "N/A"):
                questions.append({
                    "tier": 3,
                    "category": "cross-component-integration",
                    "question": f"How does {comp} interact with {other}?",
                    "expected_answer": f"{comp} interacts with {other}: {purpose_text}",
                    "expected_answerable": True,
                    "source_files": [
                        f"architecture/{version}/{comp}.md",
                        f"architecture/{version}/{other}.md",
                    ],
                    "source_excerpt": excerpt(doc_comp, other),
                    "expected_arch_query_commands": [
                        f"arch-query deps {comp}",
                        f"arch-query deps {other}",
                    ],
                    "tags": ["integration", comp, other],
                })

    return questions


def generate_tier4(arch_dir: Path, version: str, components: list[str]) -> list[dict]:
    questions = []
    all_dirs = get_all_directories(arch_dir)
    symlinks = get_symlinks(arch_dir)
    overlays = get_overlays(arch_dir)

    dir_list = ", ".join(all_dirs)
    questions.append({
        "tier": 4,
        "category": "navigation",
        "question": "What architecture directories are available (including non-release)?",
        "expected_answer": f"Available directories: {dir_list}.",
        "expected_answerable": True,
        "source_files": [f"architecture/{version}/PLATFORM.md"],
        "source_excerpt": f"Directories: {dir_list}",
        "expected_arch_query_commands": ["arch-query versions"],
        "tags": ["versions"],
    })

    for alias, target in symlinks.items():
        questions.append({
            "tier": 4,
            "category": "navigation",
            "question": f"What version does the '{alias}' alias point to?",
            "expected_answer": f"The '{alias}' alias points to {target}.",
            "expected_answerable": True,
            "source_files": [f"architecture/{alias}"],
            "source_excerpt": f"Symlink: {alias} -> {target}",
            "expected_arch_query_commands": ["arch-query versions"],
            "tags": ["symlink", alias],
        })

    questions.append({
        "tier": 4,
        "category": "navigation",
        "question": f"How many component docs are in {version}?",
        "expected_answer": f"There are {len(components)} component docs in {version}.",
        "expected_answerable": True,
        "source_files": [f"architecture/{version}/PLATFORM.md"],
        "source_excerpt": f"Component Count: {len(components)}",
        "expected_arch_query_commands": ["arch-query list"],
        "tags": ["count"],
    })

    for comp in ["kserve", "vllm-cpu", "data-science-pipelines", "mlflow", "model-registry"]:
        if comp in components:
            questions.append({
                "tier": 4,
                "category": "navigation",
                "question": f"Where is the {comp} component doc in the architecture directory?",
                "expected_answer": f"architecture/{version}/{comp}.md",
                "expected_answerable": True,
                "source_files": [f"architecture/{version}/{comp}.md"],
                "source_excerpt": f"File: architecture/{version}/{comp}.md",
                "expected_arch_query_commands": [f"arch-query component {comp}"],
                "tags": ["path", comp],
            })

    questions.append({
        "tier": 4,
        "category": "navigation",
        "question": f"Does architecture/{version}/ have a components/ subdirectory?",
        "expected_answer": (
            f"No. Component docs are stored directly in architecture/{version}/ "
            f"as {{component-name}}.md files. There is no components/ subdirectory."
        ),
        "expected_answerable": True,
        "source_files": [f"architecture/{version}/PLATFORM.md"],
        "source_excerpt": f"Component docs are at architecture/{version}/{{name}}.md, not in a components/ subdirectory.",
        "expected_arch_query_commands": ["arch-query list"],
        "tags": ["negative", "structure"],
    })

    if overlays:
        overlay_names = "; ".join(f"{o['file']}: {o['title']}" for o in overlays)
        questions.append({
            "tier": 4,
            "category": "navigation",
            "question": "What overlays modify the base architecture?",
            "expected_answer": f"There are {len(overlays)} overlays: {overlay_names}.",
            "expected_answerable": True,
            "source_files": [f"overlays/{o['file']}" for o in overlays],
            "source_excerpt": overlay_names[:400],
            "expected_arch_query_commands": ["arch-query overlays"],
            "tags": ["overlays"],
        })

    questions.append({
        "tier": 4,
        "category": "navigation",
        "question": f"Where is the platform summary for {version}?",
        "expected_answer": f"architecture/{version}/PLATFORM.md",
        "expected_answerable": True,
        "source_files": [f"architecture/{version}/PLATFORM.md"],
        "source_excerpt": f"Platform summary at architecture/{version}/PLATFORM.md",
        "expected_arch_query_commands": ["arch-query platform"],
        "tags": ["platform"],
    })

    return questions


def assign_ids(questions: list[dict]) -> list[dict]:
    by_tier: dict[int, list[dict]] = defaultdict(list)
    for q in questions:
        by_tier[q["tier"]].append(q)
    result = []
    for tier in sorted(by_tier.keys()):
        for i, q in enumerate(by_tier[tier], start=1):
            q["id"] = f"t{tier}-{i:03d}"
            result.append(q)
    return result


def build_corpus_entry(q: dict) -> dict:
    entry = {
        "id": q["id"],
        "tier": q["tier"],
        "category": q["category"],
        "question": q["question"],
        "expected_answer": q["expected_answer"],
        "expected_answerable": q["expected_answerable"],
        "source_files": q.get("source_files", []),
        "source_excerpt": q.get("source_excerpt", ""),
    }
    if q.get("expected_arch_query_commands"):
        entry["expected_arch_query_commands"] = q["expected_arch_query_commands"]
    if q.get("tags"):
        entry["tags"] = q["tags"]
    return entry


def get_commit(arch_dir: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(arch_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except FileNotFoundError:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(
        description="Generate benchmark corpus from architecture-context docs"
    )
    parser.add_argument(
        "--arch-context-dir",
        default="deploy/repos/architecture-context",
    )
    parser.add_argument(
        "--output",
        default="benchmarks/arch-context/corpus-claude.yaml",
    )
    parser.add_argument(
        "--version",
        default="rhoai.next",
    )
    args = parser.parse_args()

    arch_dir = Path(args.arch_context_dir)
    version = args.version
    components = get_components(arch_dir, version)

    print(f"Architecture dir: {arch_dir}")
    print(f"Version: {version}")
    print(f"Components: {len(components)}")

    print("\nGenerating Tier 1 (inventory)...")
    t1 = generate_tier1(components, arch_dir, version)
    print(f"  {len(t1)} questions")

    print("Generating Tier 2 (fact extraction)...")
    t2 = generate_tier2(components, arch_dir, version)
    print(f"  {len(t2)} questions")

    print("Generating Tier 3 (cross-component)...")
    t3 = generate_tier3(components, arch_dir, version)
    print(f"  {len(t3)} questions")

    print("Generating Tier 4 (navigation)...")
    t4 = generate_tier4(arch_dir, version, components)
    print(f"  {len(t4)} questions")

    all_questions = t1 + t2 + t3 + t4
    all_questions = assign_ids(all_questions)

    corpus = {
        "version": "1.0",
        "architecture_context_commit": get_commit(arch_dir),
        "generated_date": str(date.today()),
        "target_version": version,
        "questions": [build_corpus_entry(q) for q in all_questions],
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(corpus, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    total = len(all_questions)
    print(f"\nWrote {total} questions to {output_path}")
    for tier in [1, 2, 3, 4]:
        count = sum(1 for q in all_questions if q["tier"] == tier)
        print(f"  Tier {tier}: {count}")


if __name__ == "__main__":
    main()
