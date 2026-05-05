---
name: bench-answer-flat
description: Answer architecture question using flat file access (Read/Glob/Grep)
allowed-tools: Read, Write, Glob, Grep
---

# Benchmark Answer — Flat File Mode

Answer an architecture-context question by reading the architecture docs directly from the filesystem. Produce a machine-readable JSON answer and a human-readable markdown summary.

## Instructions

### Inputs

You will receive the following in the prompt:

- `QUESTION` — the architecture question to answer
- `QUESTION_ID` — the corpus question ID (e.g., `t1-001`)
- `ARCH_CONTEXT_DIR` — absolute path to the architecture-context directory
- `OUTPUT_DIR` — directory to write your output files

### Constraints

- Read ONLY from `$ARCH_CONTEXT_DIR`. Do not access any other directories, repos, or external sources.
- Use Glob to discover directory structure and file names.
- Use Grep to search for terms across files.
- Use Read to examine file contents.
- If the information is not in the docs, explicitly state: "Not documented in the architecture-context." Do NOT guess or fabricate an answer.
- Cite specific file paths relative to the architecture-context root (e.g., `architecture/rhoai-3.4-ea.2/kserve.md`).

### Architecture-Context Directory Structure

The directory is organized by RHOAI release version:

- **Architecture docs:** `architecture/rhoai-{VERSION}/{component}.md`
- **Platform summary:** `architecture/rhoai-{VERSION}/PLATFORM.md`
- **Overlays:** `overlays/{NNNN}-{description}.md`
- **Symlink aliases:** `current-ga`, `early-access`, `latest-released`, `newest` (point to version dirs)

Start by listing the `architecture/` directory to see available versions, then navigate to the relevant version.

### JSON Schema

Your primary output is a JSON file conforming to this schema.

**STRICT SCHEMA RULE:** The JSON must contain ONLY the exact keys shown below — no extra fields at any level. The schema uses `additionalProperties: false` and any extra key will cause validation failure.

```json
{
  "question_id": "t1-001",
  "question": "Is InstructLab a RHOAI component?",
  "answer": "No. InstructLab is not listed in the RHOAI component inventory. It is a RHEL AI component.",
  "answerable": false,
  "sources_cited": [
    {
      "source": "architecture/rhoai-3.4-ea.2/PLATFORM.md",
      "excerpt": "Component Count: 45 ... [InstructLab not in list]"
    }
  ],
  "confidence": "high"
}
```

Field definitions:

- `question_id`: string — the corpus question ID from `QUESTION_ID`
- `question`: string — the question text from `QUESTION`
- `answer`: string — your answer, or "Not documented in the architecture-context." if the information is not present
- `answerable`: boolean — `true` if you found the answer in the docs, `false` if the information is not documented
- `sources_cited`: array of objects, each with:
  - `source`: string — file path relative to architecture-context root (e.g., `architecture/rhoai-3.4-ea.2/kserve.md`)
  - `excerpt`: string — the relevant passage from that file (max 200 chars)
- `confidence`: string enum — one of:
  - `high` — found an exact answer in the docs
  - `medium` — inferred from partial information across one or more docs
  - `low` — uncertain; docs are ambiguous or cover the topic only tangentially

### Steps

1. **Understand the question.** Determine what kind of information is being asked for: component existence, a specific fact (port, CRD, API), a cross-component relationship, or directory navigation.

2. **Navigate the architecture directory.** Use Glob to list available versions and components. Identify the most relevant version for the question (default to the latest or `rhoai.next` if the question doesn't specify).

3. **Search for relevant content.** Use Grep to find mentions of the subject across component docs. Use Read to examine the most relevant files.

4. **Formulate your answer.** Base it strictly on what the docs say. If the docs don't cover the topic, say so.

5. **Cite your sources.** List every file you read that contributed to your answer, with the relevant excerpt.

6. **Assess your confidence.** High if the docs directly answer the question, medium if you had to infer, low if the docs are unclear.

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
- **{file path}**: {excerpt}

## Confidence: {high/medium/low}
## Answerable: {yes/no}
```
