"""Statistical analysis of pipeline quality measures vs fix outcomes."""

import json
import math
from pathlib import Path

import numpy as np
from scipy import stats as sp_stats

from lib.phases import ISSUES_DIR

PHASE_SUFFIXES = ["completeness", "context-map", "fix-attempt", "test-plan"]

# Map string confidence values to ordinal numbers
_CONFIDENCE_MAP = {"low": 1, "medium": 2, "high": 3}


def _parse_confidence(val) -> float | None:
    """Normalise confidence to a 0-1 float (or None)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    val_lower = str(val).strip().lower()
    ordinal = _CONFIDENCE_MAP.get(val_lower)
    if ordinal is not None:
        return ordinal / 3.0  # low=0.33, medium=0.67, high=1.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def load_stats_data() -> list[dict]:
    """Collect per-issue feature vectors for statistical analysis.

    Returns a list of dicts, one per issue that has at least completeness
    and context-map outputs.  Fix-attempt and test-plan fields may be None
    for issues that were skipped.
    """
    if not ISSUES_DIR.exists():
        return []

    rows: list[dict] = []

    for comp_path in sorted(ISSUES_DIR.glob("RHOAIENG-*.completeness.json")):
        key = comp_path.name.split(".")[0]

        comp = _safe_load(comp_path)
        ctx = _safe_load(ISSUES_DIR / f"{key}.context-map.json")
        fix = _safe_load(ISSUES_DIR / f"{key}.fix-attempt.json")
        tp = _safe_load(ISSUES_DIR / f"{key}.test-plan.json")

        if comp is None or ctx is None:
            continue

        # --- Completeness ---
        bug_quality = comp.get("overall_score")
        triage = comp.get("triage_recommendation", "")

        # --- Context map ---
        context_rating = ctx.get("overall_rating", "")
        ch = ctx.get("context_helpfulness") or {}
        context_helpfulness = ch.get("overall_score")
        coverage = (ch.get("coverage") or {}).get("score")
        depth = (ch.get("depth") or {}).get("score")
        freshness = (ch.get("freshness") or {}).get("score")

        # Architecture doc / source checkout availability
        entries = ctx.get("context_entries", [])
        has_arch_doc = any(
            e.get("architecture_doc", "not found") != "not found"
            for e in entries
        )
        has_source_checkout = any(
            e.get("source_checkout", "not found") != "not found"
            for e in entries
        )
        component_count = len(entries)
        full_count = sum(1 for e in entries if e.get("rating") == "full-context")
        partial_count = sum(1 for e in entries if e.get("rating") == "partial-context")
        full_context_ratio = full_count / component_count if component_count else 0.0

        # --- Fix attempt ---
        fix_recommendation = fix.get("recommendation", "") if fix else ""
        fix_confidence_raw = fix.get("confidence") if fix else None
        fix_confidence = _parse_confidence(fix_confidence_raw)
        is_fixable = 1 if fix_recommendation == "ai-fixable" else (0 if fix else None)

        # --- Test plan ---
        test_effort = tp.get("effort_estimate", "") if tp else ""

        rows.append({
            "key": key,
            # Numeric predictors
            "bug_quality": bug_quality,
            "context_helpfulness": context_helpfulness,
            "coverage": coverage,
            "depth": depth,
            "freshness": freshness,
            "component_count": component_count,
            "full_context_ratio": full_context_ratio,
            "fix_confidence": fix_confidence,
            # Binary predictors
            "has_arch_doc": has_arch_doc,
            "has_source_checkout": has_source_checkout,
            # Categorical
            "triage": triage,
            "context_rating": context_rating,
            "fix_recommendation": fix_recommendation,
            "test_effort": test_effort,
            # Derived binary outcome
            "is_fixable": is_fixable,
        })

    return rows


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def _to_array(rows: list[dict], field: str, require_not_none: bool = True) -> tuple[np.ndarray, list[int]]:
    """Extract a numeric array + indices of valid entries."""
    vals = []
    idxs = []
    for i, r in enumerate(rows):
        v = r.get(field)
        if v is None and require_not_none:
            continue
        if v is None:
            continue
        try:
            vals.append(float(v))
            idxs.append(i)
        except (TypeError, ValueError):
            continue
    return np.array(vals, dtype=float), idxs


def compute_correlation_matrix(rows: list[dict]) -> dict:
    """Spearman rank correlation matrix for numeric variables.

    Returns {fields: [...], matrix: [[rho, ...], ...], pvalues: [[p, ...], ...]}.
    """
    fields = [
        "bug_quality", "context_helpfulness", "coverage", "depth",
        "freshness", "full_context_ratio", "component_count", "fix_confidence",
    ]

    # Only use rows that have all fields
    valid_rows = []
    for r in rows:
        if all(r.get(f) is not None for f in fields):
            valid_rows.append(r)

    n = len(valid_rows)
    k = len(fields)
    if n < 5:
        return {"fields": fields, "matrix": [], "pvalues": [], "n": n}

    data = np.array([[r[f] for f in fields] for r in valid_rows], dtype=float)

    rho_matrix = []
    p_matrix = []
    for i in range(k):
        rho_row = []
        p_row = []
        for j in range(k):
            if i == j:
                rho_row.append(1.0)
                p_row.append(0.0)
            else:
                rho, p = sp_stats.spearmanr(data[:, i], data[:, j])
                rho_row.append(round(rho, 3))
                p_row.append(round(p, 4))
        rho_matrix.append(rho_row)
        p_matrix.append(p_row)

    return {"fields": fields, "matrix": rho_matrix, "pvalues": p_matrix, "n": n}


def compute_chi_squared_tests(rows: list[dict]) -> list[dict]:
    """Chi-squared independence tests for categorical pairs.

    Returns a list of test result dicts.
    """
    results = []

    pairs = [
        ("context_rating", "fix_recommendation", "Context Rating vs Fix Recommendation"),
        ("triage", "fix_recommendation", "Triage Recommendation vs Fix Recommendation"),
        ("context_rating", "test_effort", "Context Rating vs Test Effort"),
    ]

    # Also test binary predictors
    binary_pairs = [
        ("has_arch_doc", "fix_recommendation", "Has Architecture Doc vs Fix Recommendation"),
        ("has_source_checkout", "fix_recommendation", "Has Source Checkout vs Fix Recommendation"),
        ("has_arch_doc", "test_effort", "Has Architecture Doc vs Test Effort"),
    ]

    for var1, var2, label in pairs + binary_pairs:
        # Build contingency table
        valid = [(r[var1], r[var2]) for r in rows
                 if r.get(var1) is not None and r.get(var1) != ""
                 and r.get(var2) is not None and r.get(var2) != ""]
        if len(valid) < 10:
            continue

        # Get unique categories
        cats1 = sorted(set(str(v[0]) for v in valid))
        cats2 = sorted(set(str(v[1]) for v in valid))

        cat1_idx = {c: i for i, c in enumerate(cats1)}
        cat2_idx = {c: i for i, c in enumerate(cats2)}

        table = np.zeros((len(cats1), len(cats2)), dtype=int)
        for v1, v2 in valid:
            table[cat1_idx[str(v1)], cat2_idx[str(v2)]] += 1

        # Skip if any dimension is 1
        if table.shape[0] < 2 or table.shape[1] < 2:
            continue

        chi2, p, dof, expected = sp_stats.chi2_contingency(table)

        # Cramér's V for effect size
        n_obs = table.sum()
        min_dim = min(table.shape[0] - 1, table.shape[1] - 1)
        cramers_v = math.sqrt(chi2 / (n_obs * min_dim)) if min_dim > 0 and n_obs > 0 else 0.0

        results.append({
            "label": label,
            "var1": var1,
            "var2": var2,
            "chi2": round(chi2, 2),
            "p_value": round(p, 4),
            "dof": dof,
            "cramers_v": round(cramers_v, 3),
            "n": len(valid),
            "significant": p < 0.05,
            "rows": cats1,
            "cols": cats2,
            "table": table.tolist(),
        })

    return results


def compute_group_tests(rows: list[dict]) -> list[dict]:
    """Kruskal-Wallis and Mann-Whitney U tests.

    Tests whether numeric predictors differ across fix_recommendation groups,
    and whether binary predictors (arch doc, source checkout) associate with
    different numeric outcomes.
    """
    results = []

    # --- Kruskal-Wallis: numeric predictor across fix_recommendation groups ---
    numeric_fields = [
        ("bug_quality", "Bug Quality Score"),
        ("context_helpfulness", "Context Helpfulness Score"),
        ("coverage", "Context Coverage"),
        ("depth", "Context Depth"),
        ("freshness", "Context Freshness"),
        ("full_context_ratio", "Full Context Ratio"),
    ]

    for field, label in numeric_fields:
        groups: dict[str, list[float]] = {}
        for r in rows:
            rec = r.get("fix_recommendation")
            val = r.get(field)
            if rec and val is not None:
                groups.setdefault(rec, []).append(float(val))

        group_names = sorted(groups.keys())
        group_arrays = [groups[g] for g in group_names]
        # Need at least 2 groups with 2+ observations each
        valid_groups = [(n, a) for n, a in zip(group_names, group_arrays) if len(a) >= 2]
        if len(valid_groups) < 2:
            continue

        valid_names, valid_arrays = zip(*valid_groups)
        h_stat, p = sp_stats.kruskal(*valid_arrays)

        group_stats = []
        for name, arr in zip(valid_names, valid_arrays):
            group_stats.append({
                "group": name,
                "n": len(arr),
                "median": round(float(np.median(arr)), 1),
                "mean": round(float(np.mean(arr)), 1),
                "std": round(float(np.std(arr)), 1),
                "q1": round(float(np.percentile(arr, 25)), 1),
                "q3": round(float(np.percentile(arr, 75)), 1),
            })

        results.append({
            "test": "kruskal-wallis",
            "label": f"{label} by Fix Recommendation",
            "field": field,
            "grouping": "fix_recommendation",
            "h_stat": round(h_stat, 2),
            "p_value": round(p, 4),
            "significant": p < 0.05,
            "groups": group_stats,
        })

    # --- Mann-Whitney U: binary predictor vs numeric outcome ---
    binary_tests = [
        ("has_arch_doc", "fix_confidence", "Architecture Doc vs Fix Confidence"),
        ("has_source_checkout", "fix_confidence", "Source Checkout vs Fix Confidence"),
        ("has_arch_doc", "context_helpfulness", "Architecture Doc vs Context Helpfulness"),
        ("has_source_checkout", "context_helpfulness", "Source Checkout vs Context Helpfulness"),
        ("has_arch_doc", "bug_quality", "Architecture Doc vs Bug Quality"),
    ]

    for binary_field, numeric_field, label in binary_tests:
        group_true = []
        group_false = []
        for r in rows:
            bval = r.get(binary_field)
            nval = r.get(numeric_field)
            if bval is None or nval is None:
                continue
            if bval:
                group_true.append(float(nval))
            else:
                group_false.append(float(nval))

        if len(group_true) < 2 or len(group_false) < 2:
            continue

        u_stat, p = sp_stats.mannwhitneyu(group_true, group_false, alternative="two-sided")

        results.append({
            "test": "mann-whitney-u",
            "label": label,
            "field": numeric_field,
            "grouping": binary_field,
            "u_stat": round(u_stat, 2),
            "p_value": round(p, 4),
            "significant": p < 0.05,
            "groups": [
                {
                    "group": f"{binary_field}=True",
                    "n": len(group_true),
                    "median": round(float(np.median(group_true)), 1),
                    "mean": round(float(np.mean(group_true)), 1),
                },
                {
                    "group": f"{binary_field}=False",
                    "n": len(group_false),
                    "median": round(float(np.median(group_false)), 1),
                    "mean": round(float(np.mean(group_false)), 1),
                },
            ],
        })

    return results


def compute_logistic_regression(rows: list[dict]) -> dict | None:
    """Simple logistic regression predicting is_fixable from numeric predictors.

    Uses iteratively reweighted least squares (no sklearn needed).
    Returns coefficients, odds ratios, and pseudo-R².
    """
    features = [
        "bug_quality", "context_helpfulness", "full_context_ratio",
        "has_arch_doc", "has_source_checkout", "component_count",
    ]

    # Collect valid rows
    X_rows = []
    y_vals = []
    for r in rows:
        if r.get("is_fixable") is None:
            continue
        vals = []
        skip = False
        for f in features:
            v = r.get(f)
            if v is None:
                skip = True
                break
            vals.append(float(v))
        if skip:
            continue
        X_rows.append(vals)
        y_vals.append(float(r["is_fixable"]))

    if len(X_rows) < 20:
        return None

    X = np.array(X_rows, dtype=float)
    y = np.array(y_vals, dtype=float)

    # Standardise numeric features for stable convergence
    means = X.mean(axis=0)
    stds = X.std(axis=0)
    stds[stds == 0] = 1.0
    X_std = (X - means) / stds

    # Add intercept
    n, k = X_std.shape
    X_design = np.column_stack([np.ones(n), X_std])

    # IRLS logistic regression
    beta = np.zeros(k + 1)
    for _ in range(50):
        z = X_design @ beta
        z = np.clip(z, -20, 20)
        p = 1.0 / (1.0 + np.exp(-z))
        W = p * (1 - p)
        W = np.maximum(W, 1e-10)
        W_diag = np.diag(W)
        try:
            H = X_design.T @ W_diag @ X_design
            grad = X_design.T @ (y - p)
            beta += np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            break

    # Predictions and pseudo-R²
    z_final = X_design @ beta
    z_final = np.clip(z_final, -20, 20)
    p_final = 1.0 / (1.0 + np.exp(-z_final))

    # Log-likelihood
    eps = 1e-10
    ll_model = np.sum(y * np.log(p_final + eps) + (1 - y) * np.log(1 - p_final + eps))
    p_null = y.mean()
    ll_null = n * (p_null * math.log(p_null + eps) + (1 - p_null) * math.log(1 - p_null + eps))
    pseudo_r2 = 1 - (ll_model / ll_null) if ll_null != 0 else 0.0

    # Standard errors from inverse Hessian
    try:
        cov = np.linalg.inv(H)
        se = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        se = np.full(k + 1, float("nan"))

    # Build results (convert back to original scale for interpretability)
    coefficients = []
    for i, f in enumerate(["intercept"] + features):
        idx = i
        coef_std = beta[idx]
        se_val = se[idx]
        # Wald z-test
        z_val = coef_std / se_val if se_val > 0 and not np.isnan(se_val) else 0.0
        p_val = 2 * (1 - sp_stats.norm.cdf(abs(z_val)))
        odds_ratio = math.exp(coef_std) if abs(coef_std) < 20 else float("inf")

        coefficients.append({
            "feature": f,
            "coefficient": round(coef_std, 4),
            "std_error": round(se_val, 4) if not np.isnan(se_val) else None,
            "z_value": round(z_val, 3),
            "p_value": round(p_val, 4),
            "odds_ratio": round(odds_ratio, 3),
            "significant": p_val < 0.05,
        })

    # Accuracy
    predictions = (p_final >= 0.5).astype(float)
    accuracy = float(np.mean(predictions == y))

    return {
        "n": n,
        "pseudo_r2": round(pseudo_r2, 4),
        "accuracy": round(accuracy, 3),
        "base_rate": round(float(y.mean()), 3),
        "coefficients": coefficients,
        "note": "Coefficients are on standardised features; odds ratios show effect of 1 SD change.",
    }


def _to_native(obj):
    """Recursively convert numpy types to Python natives for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def compute_all_stats() -> dict:
    """Run all analyses and return a single results dict for the template."""
    rows = load_stats_data()

    if not rows:
        return {"n_issues": 0, "error": "No issue data found."}

    n_with_fix = sum(1 for r in rows if r.get("fix_recommendation"))
    n_fixable = sum(1 for r in rows if r.get("is_fixable") == 1)

    result = {
        "n_issues": len(rows),
        "n_with_fix": n_with_fix,
        "n_fixable": n_fixable,
        "correlation": compute_correlation_matrix(rows),
        "chi_squared": compute_chi_squared_tests(rows),
        "group_tests": compute_group_tests(rows),
        "logistic": compute_logistic_regression(rows),
    }
    return _to_native(result)
