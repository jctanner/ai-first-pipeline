---
name: bench-answer-query
description: Answer architecture question using arch-query CLI
allowed-tools: Bash, Write
---

# Benchmark Answer — arch-query Mode

Answer an architecture-context question using the `arch-query` CLI tool. Produce a machine-readable JSON answer and a human-readable markdown summary.

## Instructions

### Inputs

You will receive the following in the prompt:

- `QUESTION` — the architecture question to answer
- `QUESTION_ID` — the corpus question ID (e.g., `t1-001`)
- `ARCH_QUERY_BIN` — path to the arch-query binary (e.g., `/usr/local/bin/arch-query`). Architecture data is embedded in the binary — no `--base-dir` needed.
- `OUTPUT_DIR` — directory to write your output files

### Constraints

- Use ONLY `arch-query` subcommands to look up architecture context. Do NOT use `cat`, `ls`, `find`, `grep`, `head`, `tail`, or any other command to read architecture-context files directly.
- Do NOT use Read, Glob, or Grep tools (they are not available to you).
- If arch-query does not return the information you need, state: "Not documented in the architecture-context." Do NOT guess or fabricate an answer.
- Cite the arch-query commands you used as your sources.

### Available arch-query Subcommands

Always invoke arch-query using `$ARCH_QUERY_BIN` (which includes `--base-dir`):

```
$ARCH_QUERY_BIN search <term>                    Find components by name or purpose
$ARCH_QUERY_BIN component <name>                 Component fact sheet (CRDs, ports, deps, constraints)
$ARCH_QUERY_BIN component <name> --raw           Full markdown doc for deep questions
$ARCH_QUERY_BIN exists <name>                    Check if component is in RHOAI inventory (exit 0/1)
$ARCH_QUERY_BIN list                             List all components grouped by domain
$ARCH_QUERY_BIN list --names-only                Component names only, one per line
$ARCH_QUERY_BIN deps <name>                      Dependency graph (forward + reverse)
$ARCH_QUERY_BIN crds [component]                 CRD index (all or per-component)
$ARCH_QUERY_BIN ports [component]                Port index (all or per-component)
$ARCH_QUERY_BIN platform                         Condensed platform summary
$ARCH_QUERY_BIN overlays                         Active overlays and affected components
$ARCH_QUERY_BIN versions                         Available versions with aliases
$ARCH_QUERY_BIN diff <component> <ver-a> <ver-b> Structured diff between versions
$ARCH_QUERY_BIN diff --all <ver-a> <ver-b>       Platform-wide diff between versions
$ARCH_QUERY_BIN grep <term>                      Deep search across all parsed fields
$ARCH_QUERY_BIN --version <ver> <subcommand>     Query a specific version
```

### Strategy by Question Type

**Tier 1 — Inventory lookup** ("Is X a RHOAI component?"):
- Start with `arch-query exists <name>`
- If not found, try `arch-query search <term>` with alternate names
- For "list all components" questions, use `arch-query list`

**Tier 2 — Fact extraction** ("What port does X use?", "What CRDs does X manage?"):
- Use `arch-query component <name>` for the fact sheet
- Use `arch-query crds <name>` or `arch-query ports <name>` for specific lookups
- If the fact sheet doesn't have enough detail, use `arch-query component <name> --raw`

**Tier 3 — Cross-component integration** ("How do X and Y interact?"):
- Use `arch-query deps <name>` to find relationships
- Use `arch-query component <name>` on each component involved
- Use `arch-query grep <term>` to find cross-references

**Tier 4 — Navigation** ("What versions exist?", "Where are the docs?"):
- Use `arch-query versions` for version listing
- Use `arch-query list` for component inventory
- Use `arch-query platform` for platform overview

### JSON Schema

Your primary output is a JSON file conforming to this schema.

**STRICT SCHEMA RULE:** The JSON must contain ONLY the exact keys shown below — no extra fields at any level. The schema uses `additionalProperties: false` and any extra key will cause validation failure.

```json
{
  "question_id": "t1-001",
  "question": "Is InstructLab a RHOAI component?",
  "answer": "No. InstructLab is not found in the RHOAI component inventory.",
  "answerable": false,
  "sources_cited": [
    {
      "source": "arch-query exists InstructLab",
      "excerpt": "Not found in RHOAI component inventory. Closest matches: none."
    }
  ],
  "confidence": "high"
}
```

Field definitions:

- `question_id`: string — the corpus question ID from `QUESTION_ID`
- `question`: string — the question text from `QUESTION`
- `answer`: string — your answer, or "Not documented in the architecture-context." if the information is not present
- `answerable`: boolean — `true` if arch-query returned the answer, `false` if the information is not documented
- `sources_cited`: array of objects, each with:
  - `source`: string — the arch-query command you ran (e.g., `arch-query component kserve`, `arch-query exists InstructLab`)
  - `excerpt`: string — the relevant portion of arch-query's output (max 200 chars)
- `confidence`: string enum — one of:
  - `high` — arch-query returned an exact answer
  - `medium` — inferred from partial information across multiple arch-query calls
  - `low` — uncertain; arch-query output was ambiguous or only tangentially relevant

### Steps

1. **Understand the question.** Determine the question type (inventory, fact, integration, navigation) and plan which arch-query subcommands to use.

2. **Query arch-query.** Run the appropriate subcommands. Start with the most targeted command for the question type.

3. **Formulate your answer.** Base it strictly on arch-query output. If arch-query doesn't return the information, say so.

4. **Cite your sources.** List every arch-query command you ran that contributed to your answer, with the relevant excerpt from the output.

5. **Assess your confidence.** High if arch-query directly answered, medium if you combined multiple outputs, low if the output was unclear.

### Output Format

Write **two files** in `OUTPUT_DIR`:

1. **`{QUESTION_ID}.json`** — the JSON object described above
2. **`{QUESTION_ID}.md`** — a human-readable rendering:

```markdown
# Answer: {QUESTION_ID}

## Question
{question text}

## Answer
{answer text}

## Sources
- **`{arch-query command}`**: {excerpt}

## Confidence: {high/medium/low}
## Answerable: {yes/no}
```
