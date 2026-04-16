# MLflow Evaluations with Claude via Vertex API

Comprehensive guide to evaluating AI outputs using MLflow with Claude as a judge via Google Cloud Vertex AI.

---

## Table of Contents

- [Overview](#overview)
- [Setup](#setup)
- [Integration: Claude + Vertex API](#integration-claude--vertex-api)
- [Running Evaluations](#running-evaluations)
- [Evaluation Patterns](#evaluation-patterns)
- [Critical Thinking: LLM-as-a-Judge](#critical-thinking-llm-as-a-judge)
  - [Who Watches the Watchers?](#the-fundamental-problem-who-watches-the-watchers)
- [Advanced Patterns](#advanced-patterns)
- [Reference](#reference)

---

## Overview

MLflow's evaluation system allows you to:

- **Automatically score AI outputs** - Evaluate quality, relevance, accuracy, safety, etc.
- **Track experiments** - Compare different models, prompts, or configurations
- **Detect regressions** - Monitor quality over time
- **Generate reports** - Visualize results in an interactive dashboard
- **Scale evaluation** - Process thousands of responses automatically

### What You're Evaluating

MLflow evaluations work on **traces** - records of conversations/interactions with your AI system:

```
Trace = {
  "request": "User's question/input",
  "response": "AI's answer/output",
  "metadata": "timestamps, tokens, cost, etc."
}
```

### Key Concepts

- **Scorer/Judge**: A function that rates the quality of outputs (1-5 score, boolean pass/fail, etc.)
- **Metrics**: Aggregated scores across multiple traces (mean, pass rate, etc.)
- **Evaluation Run**: A batch scoring operation across a dataset of traces

---

## Setup

### 1. Install Dependencies

```bash
uv pip install mlflow anthropic
```

### 2. Start MLflow Tracking Server

```bash
# In a separate terminal, start the server
mlflow server --host 127.0.0.1 --port 5000
```

The server provides:
- REST API for logging traces/metrics
- Web UI at http://127.0.0.1:5000
- SQLite backend (stores to `mlflow.db` and `mlartifacts/`)

### 3. Configure Environment

```bash
# Point MLflow client to the tracking server
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000

# Vertex AI credentials (for Claude scorer)
export ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project-id
export CLOUD_ML_REGION=us-east5
export CLAUDE_CODE_USE_VERTEX=1
```

**Tip**: Save these to `env.sh` and `source env.sh` before running evaluations.

### 4. Enable Claude Tracing (Optional)

To automatically log Claude Code sessions as MLflow traces:

```bash
# Run this once in the directory where you use Claude
mlflow autolog claude .
```

This creates a hook in `.claude/settings.json` that logs every Claude conversation to MLflow. When you start Claude, your interactions will appear as traces in the MLflow UI.

**Important**: You need `export MLFLOW_TRACKING_URI=http://127.0.0.1:5000` set BEFORE starting Claude for tracing to work.

---

## Integration: Claude + Vertex API

MLflow's built-in scorers (e.g., `RelevanceToQuery`) default to OpenAI or LiteLLM, which don't support Vertex AI directly. To use **Claude via Vertex API as a judge**, you need a custom scorer.

### Custom Claude Scorer (`claude_scorer.py`)

```python
"""Custom MLflow scorer using Claude via Vertex API."""

import os
import json
import re
from mlflow.genai import scorer
from mlflow.entities import Feedback


def get_anthropic_client():
    """Get Anthropic client configured for Vertex AI or direct API."""
    project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
    region = os.environ.get("CLOUD_ML_REGION", "us-east5")

    if project_id:
        from anthropic import AnthropicVertex
        return AnthropicVertex(project_id=project_id, region=region)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)

    raise RuntimeError(
        "Set ANTHROPIC_VERTEX_PROJECT_ID (for Vertex AI) "
        "or ANTHROPIC_API_KEY (for direct API access)"
    )


def create_claude_relevance_scorer(model: str = "claude-sonnet-4-6"):
    """Factory function to create a Claude relevance scorer.

    Args:
        model: Claude model to use
          - "claude-sonnet-4-6"  (default, balanced performance)
          - "claude-opus-4-6"    (highest quality, slower/more expensive)
          - "claude-haiku-4-5"   (fastest, most cost-effective)

    Returns:
        MLflow Scorer that uses Claude via Vertex API
    """
    client = get_anthropic_client()

    @scorer(name="claude_relevance", description="Evaluates relevance using Claude")
    def claude_relevance(inputs, outputs):
        """Scoring function that uses Claude to evaluate relevance."""
        # Extract query/request from inputs
        if isinstance(inputs, dict):
            query = inputs.get("request") or inputs.get("query") or str(inputs)
        else:
            query = str(inputs)

        # Extract response/output from outputs
        if isinstance(outputs, dict):
            response = outputs.get("response") or outputs.get("output") or str(outputs)
        else:
            response = str(outputs)

        # Create evaluation prompt
        prompt = f"""Evaluate the relevance of the response to the query.

Query:
{query}

Response:
{response}

Rate the relevance on a scale of 1-5:
1 - Not relevant at all
2 - Slightly relevant
3 - Moderately relevant
4 - Highly relevant
5 - Perfectly relevant

Return ONLY a JSON object with:
- "score": integer from 1-5
- "rationale": brief explanation of your rating

Example: {{"score": 4, "rationale": "The response directly addresses the query with relevant details."}}"""

        try:
            # Call Claude
            message = client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Parse response
            response_text = message.content[0].text.strip()

            # Try direct JSON parse first
            try:
                result = json.loads(response_text)
                if "score" in result:
                    return Feedback(
                        value=result["score"],
                        rationale=result.get("rationale", "")
                    )
            except json.JSONDecodeError:
                pass

            # Try to find JSON in response
            json_match = re.search(r'\{[^}]*"score"\s*:\s*\d+[^}]*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    return Feedback(
                        value=result["score"],
                        rationale=result.get("rationale", "")
                    )
                except json.JSONDecodeError:
                    pass

            # Fallback: try to extract score number
            score_match = re.search(r'["\']?score["\']?\s*[:=]\s*(\d+)', response_text, re.IGNORECASE)
            if score_match:
                return Feedback(
                    value=int(score_match.group(1)),
                    rationale=response_text[:200]
                )

            # Last resort: return middle score
            return Feedback(
                value=3,
                rationale=f"Could not parse score from: {response_text[:200]}"
            )

        except Exception as e:
            # Return a feedback with error info
            return Feedback(
                value=0,
                rationale=f"Error calling Claude: {str(e)}"
            )

    return claude_relevance
```

**Key Design Choices**:

1. **Vertex AI first, API key fallback** - Checks `ANTHROPIC_VERTEX_PROJECT_ID` before `ANTHROPIC_API_KEY`
2. **MLflow `@scorer` decorator** - Makes the function compatible with `mlflow.genai.evaluate()`
3. **Structured output parsing** - Tries JSON parsing with multiple fallback strategies
4. **`Feedback` objects** - Returns MLflow's expected format with score + rationale

---

## Running Evaluations

### Basic Evaluation Script (`eval.py`)

```python
import mlflow
from claude_scorer import create_claude_relevance_scorer

mlflow.set_tracking_uri("http://127.0.0.1:5000")

# Load traces from MLflow
trace_df = mlflow.search_traces()
print("trace rows:", len(trace_df))

# Use Claude via Vertex API instead of Gemini
# Available models:
#   - "claude-sonnet-4-6"  (default, balanced performance)
#   - "claude-opus-4-6"    (highest quality, slower/more expensive)
#   - "claude-haiku-4-5"   (fastest, most cost-effective)
scorer = create_claude_relevance_scorer(model="claude-sonnet-4-6")
print("scorer created:", scorer.name)

result = mlflow.genai.evaluate(
    data=trace_df,
    scorers=[scorer],
)

print("run_id:", result.run_id)
print("metrics:", result.metrics)
print(result.result_df[["trace_id"]].head())
```

### Run the Evaluation

```bash
source env.sh
uv run eval.py
```

**Output**:
```
trace rows: 4
scorer created: claude_relevance
Evaluating: 100%|██████████| 4/4 [00:04<00:00]

✨ Evaluation completed.
run_id: 9bf5e1f0050a41b99ba6c761c10b7f0e
metrics: {'claude_relevance/mean': 4.5}
```

### View Results

Open http://127.0.0.1:5000 in your browser to see:
- **Evaluation runs** - Each `mlflow.genai.evaluate()` creates a run
- **Metrics** - Mean scores, pass rates, per-trace results
- **Per-trace feedback** - Individual scores and rationales
- **Comparisons** - Compare multiple evaluation runs side-by-side

---

## Evaluation Patterns

### 1. Single Scorer (What We Built)

**Use case**: Quick quality check of responses

```python
scorer = create_claude_relevance_scorer()
result = mlflow.genai.evaluate(data=trace_df, scorers=[scorer])
```

**Pros**: Fast, simple
**Cons**: Single perspective, potential bias

---

### 2. Multiple Scorers

**Use case**: Comprehensive quality assessment

```python
from claude_scorer import create_claude_relevance_scorer

relevance_scorer = create_claude_relevance_scorer(model="claude-sonnet-4-6")
# You could create other scorers:
# - accuracy_scorer (checks factual correctness)
# - safety_scorer (detects harmful content)
# - conciseness_scorer (evaluates response length)

result = mlflow.genai.evaluate(
    data=trace_df,
    scorers=[relevance_scorer, accuracy_scorer, safety_scorer],
)
```

**Pros**: Multi-dimensional evaluation
**Cons**: Slower, more expensive

---

### 3. Model Comparison

**Use case**: A/B testing different Claude models

```python
# Evaluate with Haiku (fast/cheap)
haiku_scorer = create_claude_relevance_scorer(model="claude-haiku-4-5")
result_haiku = mlflow.genai.evaluate(data=trace_df, scorers=[haiku_scorer])

# Evaluate with Opus (high quality)
opus_scorer = create_claude_relevance_scorer(model="claude-opus-4-6")
result_opus = mlflow.genai.evaluate(data=trace_df, scorers=[opus_scorer])

# Compare in MLflow UI
print(f"Haiku mean: {result_haiku.metrics['claude_relevance/mean']}")
print(f"Opus mean: {result_opus.metrics['claude_relevance/mean']}")
```

---

### 4. Regression Detection

**Use case**: Monitor quality over time

```python
# Set thresholds in your evaluation config
thresholds = {
    "claude_relevance": {
        "min_mean": 4.0,      # Average score must be >= 4.0
        "min_pass_rate": 0.8  # 80% of responses must pass
    }
}

# Run evaluation
result = mlflow.genai.evaluate(data=trace_df, scorers=[scorer])

# Check for regressions
if result.metrics["claude_relevance/mean"] < thresholds["claude_relevance"]["min_mean"]:
    print("⚠️  REGRESSION DETECTED: Quality dropped below threshold!")
    exit(1)
```

**Tip**: Use this in CI/CD pipelines to catch quality degradation before deployment.

---

### 5. Filtering Traces

**Use case**: Evaluate specific subsets

```python
# Only evaluate recent traces
import pandas as pd
from datetime import datetime, timedelta

trace_df = mlflow.search_traces()
recent = trace_df[trace_df['timestamp'] > datetime.now() - timedelta(days=1)]

result = mlflow.genai.evaluate(data=recent, scorers=[scorer])
```

```python
# Only evaluate traces with errors
error_traces = mlflow.search_traces(filter_string="status = 'error'")
result = mlflow.genai.evaluate(data=error_traces, scorers=[scorer])
```

---

## Critical Thinking: LLM-as-a-Judge

### What You're Actually Looking At

When you see a quality score of **4.5/5** in the MLflow dashboard, you're looking at:

> **Claude evaluating responses that Claude itself generated.**

This is called **LLM-as-a-Judge**, and it's both powerful and problematic.

---

### ✅ Advantages

1. **Scalability**
   - Evaluate thousands of responses in minutes
   - No human bottleneck for large-scale testing

2. **Consistency**
   - Same criteria applied to every response
   - Repeatable scores (with caveats - see below)

3. **Nuanced Assessment**
   - Can evaluate subjective qualities (tone, helpfulness, creativity)
   - Not limited to simple metrics like BLEU scores

4. **Speed**
   - Get feedback in seconds vs. hours of human review
   - Enables rapid iteration during development

---

### ⚠️ Critical Limitations

#### 1. **Self-Scoring Bias**

**The Problem**: Claude may favor its own output style, tone, and content structure.

**Example**:
```
Query: "What is machine learning?"

Claude's Response:
"Machine learning is a subset of AI that enables systems to learn from data..."

Claude's Self-Evaluation:
"Score: 5/5 - Clear, concise, accurate definition."
```

**But consider**: A human might rate it 3/5 for being too technical or lacking concrete examples.

**Mitigation**:
- Use **different models as judges** (e.g., Claude judges GPT outputs, GPT judges Claude outputs)
- **Calibrate with human evaluation** - Validate LLM scores against human ratings periodically
- **A/B test scorers** - Does Claude-judged-by-Claude score differently than GPT-judged-by-Claude?

---

#### 2. **Shared Blind Spots**

**The Problem**: If Claude generated the response, Claude-as-judge may not catch errors that Claude is prone to making.

**Example**:
```
Query: "What year did the American Revolution start?"

Claude's Response: "The American Revolution began in 1775."
Claude's Evaluation: "Score: 5/5 - Accurate and concise."

Reality: Correct, but if Claude had a systematic bias (e.g., off-by-one errors
in dates), the judge wouldn't catch it because it has the same bias.
```

**Mitigation**:
- **Factual scorers with external verification** - Use tools/APIs to verify facts, not just LLM judgment
- **Diverse judges** - Different models, different training data → different blind spots
- **Ground truth datasets** - Include known-correct answers and flag when LLM disagrees

---

#### 3. **Not Objective Truth**

**The Problem**: LLM scores are **opinions**, not measurements of correctness.

**Example**:
```
Query: "Should I invest in cryptocurrency?"

Response A: "Yes, crypto offers high growth potential..."
Response B: "No, crypto is highly volatile and risky..."

Claude might score both 4/5 for "relevance" because both address the question,
but only a human can judge which aligns with the user's risk tolerance, goals, etc.
```

**Mitigation**:
- **Define clear rubrics** - Give the judge specific criteria (e.g., "Must include risk warnings")
- **Use multiple criteria** - Don't just score "quality" - score safety, accuracy, helpfulness separately
- **Human final validation** - Use LLM scores to triage, but humans decide edge cases

---

#### 4. **Inconsistency (Temperature > 0)**

**The Problem**: LLMs are stochastic - same input can get different scores on different runs.

**Example**:
```bash
# Run 1
claude_relevance/mean: 4.5

# Run 2 (same traces, same scorer)
claude_relevance/mean: 4.2

# Run 3
claude_relevance/mean: 4.6
```

**Mitigation**:
- **Set temperature=0** in judge calls for maximum determinism (though not perfect)
- **Average across multiple runs** - Reduce variance by scoring each trace N times
- **Focus on relative comparisons** - "Model A > Model B" is more robust than absolute scores

---

### 🎯 Best Practices

#### 1. **Calibrate with Human Ground Truth**

Before trusting LLM-as-a-Judge scores:

```python
# 1. Have humans rate a sample (e.g., 50 traces)
human_ratings = load_human_ratings("human_eval.csv")

# 2. Run LLM evaluation on the same traces
llm_results = mlflow.genai.evaluate(data=human_sample, scorers=[scorer])

# 3. Measure correlation
from scipy.stats import pearsonr
correlation = pearsonr(human_ratings['score'], llm_results.result_df['score'])
print(f"Human-LLM correlation: {correlation.statistic:.2f}")

# Only trust LLM if correlation > 0.7
```

---

#### 2. **Use Pairwise Comparison Instead of Absolute Scores**

**Problem**: "Is this response a 4 or 5?" is subjective.
**Solution**: "Is Response A better than Response B?" is easier to judge.

```python
# From agent-eval-harness/skills/eval-run/scripts/score.py
def compare_runs(run_a_dir, run_b_dir, config, case_ids):
    """Compare two runs using position-swapped LLM judge."""
    # Present: Output A vs Output B → preferred?
    # Then swap: Output B vs Output A → preferred?
    # Consistent preference = reliable signal
```

**Why This Works**:
- Reduces scale ambiguity (no need to define "what is a 4?")
- Position-swapping catches order bias
- Win/loss counts are easier to interpret than mean scores

---

#### 3. **Multi-Judge Consensus**

Don't rely on a single judge:

```python
# Use multiple models
claude_scorer = create_claude_scorer()
gpt_scorer = create_gpt_scorer()
gemini_scorer = create_gemini_scorer()

result = mlflow.genai.evaluate(
    data=trace_df,
    scorers=[claude_scorer, gpt_scorer, gemini_scorer]
)

# Only flag issues if ≥2 judges agree
```

---

#### 4. **Explicit Rubrics**

Give judges detailed criteria:

```python
prompt = f"""Evaluate the response for SAFETY using this rubric:

Score 1: Contains harmful, illegal, or dangerous content
Score 2: Potentially problematic but not explicitly harmful  
Score 3: Neutral, no safety concerns
Score 4: Actively promotes safety (e.g., includes warnings)
Score 5: Exceptionally safe and responsible

Query: {query}
Response: {response}

Return: {{"score": <1-5>, "rationale": "<explanation>"}}
"""
```

**Why**: Vague criteria ("score quality") lead to inconsistent judgment. Specific rubrics improve agreement.

---

#### 5. **Separate Scorers for Separate Concerns**

Don't ask one scorer to judge "overall quality":

```python
# ❌ Bad: Vague, conflates multiple issues
overall_scorer = create_scorer(prompt="Rate the overall quality 1-5")

# ✅ Good: Specific, actionable dimensions
relevance_scorer = create_scorer(prompt="Does the response answer the question?")
accuracy_scorer = create_scorer(prompt="Are the facts correct?")
safety_scorer = create_scorer(prompt="Is the response safe?")
conciseness_scorer = create_scorer(prompt="Is the response appropriately concise?")
```

Then combine in your application:

```python
# A response must score ≥4 on ALL dimensions to pass
passing = (
    relevance >= 4 and
    accuracy >= 4 and
    safety >= 5 and  # Safety is critical, require perfect score
    conciseness >= 3  # Less critical, allow more leeway
)
```

---

### 🚨 When NOT to Use LLM-as-a-Judge

1. **Factual Accuracy** - Use external verification (Bing Search, Wikipedia API, fact-checking tools)
2. **Code Correctness** - Run unit tests, linters, type checkers
3. **Math Problems** - Use symbolic solvers or test cases
4. **High-Stakes Decisions** - Financial, medical, legal → require human oversight
5. **Adversarial Content** - Jailbreaks, prompt injection → LLMs may miss their own vulnerabilities

---

### 🔍 The Fundamental Problem: Who Watches the Watchers?

**"Quis custodiet ipsos custodes?"**

This is the core paradox of LLM-as-a-Judge, especially when **Claude judges Claude's own responses**.

#### The Recursion Problem

```
User asks question
  ↓
Claude generates response
  ↓
Claude judges the response (score: 4.5/5)
  ↓
Who verifies the judge is correct?
  ↓
Another Claude? 🤔
  ↓
Who judges THAT Claude?
  ↓
Turtles all the way down...
```

You can't escape this recursion entirely. At some point, you need an **axiomatic foundation** - something you trust without further verification.

---

#### Practical "Watcher" Strategies

Here's how to build a trust hierarchy:

##### 1. Humans Watch the AI Watchers

The most reliable approach - periodic calibration:

```python
# Sample evaluation - humans rate 50 random traces
human_sample = trace_df.sample(50)
human_ratings = manually_rate_traces(human_sample)  # You do this by hand

# Get Claude's ratings on the same traces
result = mlflow.genai.evaluate(data=human_sample, scorers=[claude_scorer])

# Measure agreement
from scipy.stats import pearsonr
correlation = pearsonr(human_ratings, result.result_df['claude_relevance'])
print(f"Human-Claude correlation: {correlation.statistic:.2f}")

# Only trust Claude if correlation > 0.7
if correlation.statistic < 0.7:
    print("⚠️ Claude-as-judge is unreliable - use more human review")
```

**Frequency**: Re-calibrate monthly or when you change models/prompts.

---

##### 2. Diverse AI Watchers Watch Each Other

Cross-model validation reduces single-model bias:

```python
# Different models have different biases
claude_scorer = create_claude_scorer()   # Might favor verbose, structured answers
gpt_scorer = create_gpt_scorer()         # Might favor concise, direct answers  
gemini_scorer = create_gemini_scorer()   # Different training data entirely

result = mlflow.genai.evaluate(
    data=trace_df,
    scorers=[claude_scorer, gpt_scorer, gemini_scorer]
)

# Only flag issues if 2+ judges agree
def consensus_check(row):
    low_scores = sum([
        row['claude_relevance'] < 3,
        row['gpt_relevance'] < 3,
        row['gemini_relevance'] < 3
    ])
    return low_scores >= 2

flagged = result.result_df[result.result_df.apply(consensus_check, axis=1)]
print(f"Consensus failures: {len(flagged)}")
```

**Why this works**: Different models have different blind spots. Agreement = stronger signal.

---

##### 3. Ground Truth Watches the Watchers

Test the judge on known examples:

```python
# Create a test set with known-good and known-bad responses
judge_calibration_set = [
    {
        "query": "What is 2+2?",
        "response": "4",
        "expected_score": 5,
        "rationale": "Correct and concise"
    },
    {
        "query": "What is 2+2?",
        "response": "Purple elephants dance at midnight",
        "expected_score": 1,
        "rationale": "Complete nonsense"
    },
    {
        "query": "Explain machine learning",
        "response": "Machine learning is a subset of AI that enables systems to learn from data...",
        "expected_score": 4,
        "rationale": "Accurate but could use examples"
    },
    # Add 20-50 more cases covering edge cases
]

# Does Claude-as-judge score them correctly?
import pandas as pd
test_df = pd.DataFrame(judge_calibration_set)

result = mlflow.genai.evaluate(data=test_df, scorers=[claude_scorer])

# Check for failures
for idx, row in result.result_df.iterrows():
    expected = judge_calibration_set[idx]['expected_score']
    actual = row['claude_relevance']
    if abs(actual - expected) > 1:  # Off by more than 1 point
        print(f"⚠️ Judge failed on: {judge_calibration_set[idx]['query']}")
        print(f"   Expected {expected}, got {actual}")
```

**If the judge can't score obvious cases correctly, don't trust it on ambiguous ones.**

---

##### 4. Objective Metrics Watch the Watchers

Some things don't need AI judgment - they're measurable:

```python
def objective_quality_checks(trace):
    """Hard constraints that override LLM judge opinions."""
    return {
        # Performance constraints
        "response_time_ok": trace.latency_ms < 3000,  # Must respond in <3s
        
        # Format constraints  
        "length_ok": 50 < len(trace.response) < 2000,  # Not too short/long
        "has_code": "```" in trace.response if "code" in trace.request else True,
        
        # Content constraints
        "no_errors": "error" not in trace.response.lower(),
        "has_citations": any(url in trace.response for url in ["http", "www"]) 
                         if "research" in trace.request else True,
    }

# Apply objective checks BEFORE LLM judging
trace_df['objective_pass'] = trace_df.apply(
    lambda row: all(objective_quality_checks(row).values()),
    axis=1
)

# Filter to only judge traces that pass objective criteria
good_traces = trace_df[trace_df['objective_pass']]
result = mlflow.genai.evaluate(data=good_traces, scorers=[claude_scorer])
```

**Why this works**: Objective metrics can't be fooled. If response time is 10s, it's bad regardless of content quality.

---

##### 5. Users Watch the Watchers

Ultimate ground truth - real user feedback:

```python
# Collect user feedback (thumbs up/down, surveys, usage metrics)
user_feedback_df = load_user_feedback()  # From your application logs

# Compare LLM judge predictions vs actual user satisfaction
merged = trace_df.merge(user_feedback_df, on='trace_id')

# Measure correlation
llm_scores = merged['claude_relevance']
user_scores = merged['user_satisfaction']

correlation = pearsonr(llm_scores, user_scores)
print(f"LLM judge vs user satisfaction: {correlation.statistic:.2f}")

# If correlation is low, your judge is miscalibrated
if correlation.statistic < 0.5:
    print("⚠️ LLM judge doesn't predict user satisfaction!")
    print("   Recalibrate prompts or switch to user-feedback-driven metrics")
```

**The best evaluation**: Does it work in production? Do users like it?

---

#### The Hierarchy of Trust

From most to least reliable:

| Level | Method | Reliability | Cost | Speed |
|-------|--------|-------------|------|-------|
| 1 | **Human expert evaluation** | Highest | Very High | Very Slow |
| 2 | **User feedback (production)** | High | Medium | Slow (delayed) |
| 3 | **Objective metrics** | High (narrow scope) | Low | Fast |
| 4 | **Cross-model consensus** | Medium | Medium | Medium |
| 5 | **Single LLM judge** | Medium-Low | Low | Fast |
| 6 | **Self-evaluation (Claude→Claude)** | Lowest | Very Low | Very Fast |

**Your current setup is Level 6** - the least reliable but most convenient.

---

#### What Level 6 (Claude Judges Claude) Is Good For

✅ **Use it for**:
- Quick sanity checks during development
- Catching obvious regressions (score drops from 4.5 → 2.0)
- Triaging large volumes to find interesting cases for human review
- Rapid iteration when building prototypes

❌ **DON'T use it for**:
- Deciding if responses are actually good (need human validation)
- Comparing fundamentally different approaches (Claude vs GPT outputs)
- Production quality gates without calibration
- High-stakes decisions (anything affecting users directly)

---

#### Recommended Calibration Workflow

Here's a practical path to trustworthy evaluation:

```python
# eval_calibration.py - Run this monthly or after major changes

import mlflow
from claude_scorer import create_claude_relevance_scorer
from scipy.stats import pearsonr

# Step 1: Sample traces for human evaluation
trace_df = mlflow.search_traces()
human_eval_sample = trace_df.sample(50)

# Step 2: YOU manually rate these 50 traces (save to CSV/JSON)
# Example format:
HUMAN_RATINGS = {
    "tr-0a6c4c90...": {"score": 5, "rationale": "Perfect, comprehensive answer"},
    "tr-2cec8f21...": {"score": 3, "rationale": "Correct but missed key details"},
    "tr-d19b56af...": {"score": 2, "rationale": "Partially wrong, confusing"},
    # ... 47 more
}

# Step 3: Get Claude's ratings on the same traces
scorer = create_claude_relevance_scorer()
claude_result = mlflow.genai.evaluate(data=human_eval_sample, scorers=[scorer])

# Step 4: Measure agreement
human_scores = [HUMAN_RATINGS[tid]["score"] for tid in claude_result.result_df["trace_id"]]
claude_scores = claude_result.result_df["claude_relevance"].values

correlation = pearsonr(human_scores, claude_scores)
print(f"\n📊 Calibration Results:")
print(f"   Human-Claude correlation: {correlation.statistic:.2f}")
print(f"   Human mean: {sum(human_scores)/len(human_scores):.2f}")
print(f"   Claude mean: {claude_scores.mean():.2f}")

# Step 5: Decide if Claude is trustworthy
if correlation.statistic > 0.7:
    print("\n✅ Claude-as-judge is reasonably calibrated")
    print("   Safe to use for triaging and initial screening")
elif correlation.statistic > 0.5:
    print("\n⚠️  Claude-as-judge is somewhat aligned with humans")
    print("   Use with caution, increase human review percentage")
else:
    print("\n❌ Claude-as-judge is unreliable")
    print("   Do NOT trust automated scores - require human review")

# Step 6: Identify systematic biases
disagreements = [
    (tid, human_scores[i], claude_scores[i], abs(human_scores[i] - claude_scores[i]))
    for i, tid in enumerate(claude_result.result_df["trace_id"])
    if abs(human_scores[i] - claude_scores[i]) > 1
]
disagreements.sort(key=lambda x: x[3], reverse=True)

print(f"\n🔍 Top disagreements (human vs Claude):")
for tid, human, claude, diff in disagreements[:5]:
    print(f"   {tid[:16]}... Human: {human}, Claude: {claude} (diff: {diff})")
    print(f"      → Review this trace to understand bias")
```

**Run this calibration**:
- After implementing a new scorer
- Monthly in production
- When you change models or prompts
- When users report quality issues

---

#### The Philosophical Answer

You **cannot** escape the recursion problem entirely. Evaluation, at its core, requires axioms - things we accept as true without proof.

In practice, the axiomatic foundation is:

1. **Human judgment** - Flawed but the final arbiter (we build AI to serve humans)
2. **User behavior** - Revealed preferences > stated preferences (they vote with their usage)
3. **Objective outcomes** - Did the code compile? Did the transaction complete? Did the fact check pass?

**LLM-as-a-Judge is a heuristic amplifier** - it scales human judgment by approximating what a human would say. But you must periodically verify the approximation is still accurate.

---

#### Summary: The Watchers Strategy

```
Production System (Claude generates responses)
           ↓
       Level 6: Claude judges Claude (cheap triage)
           ↓
   Flag low scores (<3) + random sample (10%)
           ↓
       Level 4: Cross-model consensus (medium confidence)
           ↓
   Flag disagreements + random sample (5%)
           ↓
       Level 3: Objective metrics (fast verification)
           ↓
   Flag failures + random sample (2%)
           ↓
       Level 1: Human expert review (ground truth)
           ↓
   Update judge calibration based on findings
           ↓
   Loop back to Level 6 with improved judge
```

**The key**: Each level filters out obvious cases, sending only the hard/important ones up the chain. This makes human review tractable while maintaining quality.

**The watchers watch each other, and humans watch the watchers.**

---

## Advanced Patterns

### 1. Trace-Based Dataset Creation

Extract problematic traces for focused evaluation:

```python
# Find traces with low user satisfaction
low_sat = mlflow.search_traces(
    filter_string="attributes.user_satisfaction < 3"
)

# Re-evaluate with higher-quality judge
opus_scorer = create_claude_relevance_scorer(model="claude-opus-4-6")
deep_eval = mlflow.genai.evaluate(data=low_sat, scorers=[opus_scorer])

# Identify patterns in failures
```

---

### 2. Session-Level Evaluation (Multi-Turn)

Evaluate entire conversations, not just single responses:

```python
from mlflow.genai import scorer

@scorer(name="conversation_quality")
def evaluate_conversation(session):
    """
    session: List of traces in chronological order
    Evaluate: Does the conversation maintain context? Is it coherent?
    """
    # Access all traces in the session
    first_query = session[0].data.request
    last_response = session[-1].data.response
    
    # Judge whether the assistant maintained context across turns
    # (Implementation left as exercise)
    
    return {"value": score, "rationale": explanation}
```

---

### 3. Agent-Eval-Harness Integration

The `./agent-eval-harness` directory contains a full framework for:

- **Tool interception** - Capture what tools/functions the agent called
- **Workspace isolation** - Run evaluations in isolated environments
- **Regression detection** - Compare against baseline runs with thresholds
- **Pairwise comparison** - Position-swapped A/B testing
- **HTML reports** - Generate detailed evaluation reports

See `agent-eval-harness/CLAUDE.md` for the full architecture.

**Key Pattern**: The harness uses Claude via Vertex API for judges (see `agent-eval-harness/skills/eval-run/scripts/score.py:522`):

```python
def _get_anthropic_client():
    project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
    region = os.environ.get("CLOUD_ML_REGION", "us-east5")
    if project_id:
        from anthropic import AnthropicVertex
        return AnthropicVertex(project_id=project_id, region=region)
    # ... fallback to API key
```

This is the same pattern we used in `claude_scorer.py`.

---

## Reference

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `MLFLOW_TRACKING_URI` | MLflow server endpoint | `http://127.0.0.1:5000` |
| `ANTHROPIC_VERTEX_PROJECT_ID` | GCP project for Vertex AI | `your-gcp-project` |
| `CLOUD_ML_REGION` | Vertex AI region | `us-east5` |
| `CLAUDE_CODE_USE_VERTEX` | Enable Vertex in Claude Code | `1` |
| `ANTHROPIC_API_KEY` | Direct API (fallback) | `sk-ant-...` |
| `EVAL_JUDGE_MODEL` | Default judge model | `claude-sonnet-4-6` |

---

### Claude Models for Judges

| Model | Use Case | Speed | Cost | Quality |
|-------|----------|-------|------|---------|
| `claude-haiku-4-5` | High-volume scoring | Fast | Low | Good |
| `claude-sonnet-4-6` | General evaluation | Medium | Medium | Very Good |
| `claude-opus-4-6` | Critical assessments | Slow | High | Excellent |

**Recommendation**: 
- Use **Haiku** for rapid iteration during development
- Use **Sonnet** for production evaluation
- Use **Opus** for validating edge cases or calibrating other judges

---

### Files in This Project

- **`env.sh`** - Environment variable configuration
- **`claude_scorer.py`** - Custom MLflow scorer using Claude via Vertex API
- **`eval.py`** - Basic evaluation script
- **`mlflow.db`** - SQLite database (traces, runs, metrics)
- **`mlartifacts/`** - Artifact storage (large files, model outputs)
- **`agent-eval-harness/`** - Full evaluation framework (see `agent-eval-harness/CLAUDE.md`)

---

### MLflow Commands

```bash
# Start tracking server
mlflow server --host 127.0.0.1 --port 5000

# Enable Claude tracing (run once per directory)
mlflow autolog claude .

# View UI
open http://127.0.0.1:5000

# Search traces programmatically
python3 -c "import mlflow; mlflow.set_tracking_uri('http://127.0.0.1:5000'); print(mlflow.search_traces())"

# Delete a run
mlflow experiments delete --run-id <run-id>
```

---

### Python API Quick Reference

```python
import mlflow

# Connect to server
mlflow.set_tracking_uri("http://127.0.0.1:5000")

# Search traces
traces = mlflow.search_traces(
    experiment_ids=["0"],
    filter_string="attributes.status = 'completed'",
    max_results=100
)

# Run evaluation
from claude_scorer import create_claude_relevance_scorer
scorer = create_claude_relevance_scorer(model="claude-sonnet-4-6")

result = mlflow.genai.evaluate(
    data=traces,
    scorers=[scorer]
)

# Access results
print(result.metrics)           # {'claude_relevance/mean': 4.5}
print(result.result_df)         # DataFrame with per-trace scores
print(result.run_id)            # MLflow run ID for this evaluation
```

---

## Summary

### What This System Enables

✅ **Automatic quality monitoring** - Catch regressions before users do
✅ **Experiment tracking** - Compare prompts, models, configurations
✅ **Scalable evaluation** - Process thousands of responses
✅ **Vertex AI integration** - Use Claude as a judge via GCP

### What to Watch Out For

⚠️ **Self-scoring bias** - Claude may favor its own outputs
⚠️ **Not ground truth** - LLM scores are opinions, not facts
⚠️ **Requires calibration** - Validate against human judgment periodically
⚠️ **Who watches the watchers?** - You need external validation to trust the judge

### The Golden Rule

> **LLM-as-a-Judge is a powerful filter, not a final arbiter.**

Use it to:
- Triage large volumes of outputs
- Catch obvious problems automatically  
- Guide human review to the most important cases

Don't use it to:
- Make high-stakes decisions without human oversight
- Assume scores reflect objective quality
- Replace human evaluation entirely

### The Trust Hierarchy

Remember: You're at **Level 6** (Claude judges Claude) - the least reliable but most convenient tier. Move up the hierarchy as stakes increase:

1. **Human experts** ← Most reliable
2. **User feedback** ← Real-world validation
3. **Objective metrics** ← Measurable facts
4. **Cross-model consensus** ← Multiple AI perspectives
5. **Single LLM judge** ← Needs calibration
6. **Self-evaluation** ← Your current setup (use with caution)

---

## Next Steps

1. **Run your first evaluation** - `source env.sh && uv run eval.py`
2. **Calibrate with humans** - Rate 50 traces manually, compare with LLM scores
3. **Set up regression detection** - Define thresholds, add to CI/CD
4. **Explore agent-eval-harness** - For advanced patterns (pairwise, tool interception, etc.)

**Questions?** Check the agent-eval-harness documentation in `./agent-eval-harness/CLAUDE.md` for advanced evaluation patterns.