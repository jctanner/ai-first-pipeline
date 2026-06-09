"""Repo name mapping between downstream (red-hat-data-services) and midstream (opendatahub-io).

RHOAI's contribution flow is:
  upstream (e.g. kserve/kserve)
    -> midstream (opendatahub-io/kserve)
      -> downstream (red-hat-data-services/kserve)

Fixes target midstream.  This module maps downstream component names
to their midstream org/repo, handles naming exceptions, and provides
a clone helper.
"""

import logging
import re
import subprocess
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Naming exceptions: downstream name -> (midstream_org, midstream_repo)
# ---------------------------------------------------------------------------

MIDSTREAM_EXCEPTIONS: dict[str, tuple[str, str]] = {
    "rhods-operator": ("opendatahub-io", "opendatahub-operator"),
    "data-science-pipelines": ("opendatahub-io", "data-science-pipelines"),
    "data-science-pipelines-operator": ("opendatahub-io", "data-science-pipelines-operator"),
}

# ---------------------------------------------------------------------------
# Downstream-only repos (no midstream equivalent — skip cloning)
# ---------------------------------------------------------------------------

DOWNSTREAM_ONLY: set[str] = {
    "RHOAI-Build-Config",
    "rhoai-additional-images",
    "konflux-central",
    "model-metadata-collection",
    # Upstream projects bundled into notebook images — no midstream fork
    "jupyterlab-git",
    "jupyterlab-trash",
}

# ---------------------------------------------------------------------------
# Repos where opendatahub-io is itself a midstream fork of a true upstream
# ---------------------------------------------------------------------------

KNOWN_UPSTREAMS: dict[str, str] = {
    "kserve": "kserve/kserve",
    "kuberay": "ray-project/kuberay",
    "argo-workflows": "argoproj/argo-workflows",
    "training-operator": "kubeflow/training-operator",
    "feast": "feast-dev/feast",
    "spark-operator": "kubeflow/spark-operator",
    "MLServer": "SeldonIO/MLServer",
    "openvino_model_server": "openvinotoolkit/model_server",
    "NeMo-Guardrails": "NVIDIA/NeMo-Guardrails",
}

# ---------------------------------------------------------------------------
# Component name aliases: context-map component names that don't match the
# actual repo name.  Maps alias -> canonical downstream repo name.
# ---------------------------------------------------------------------------

COMPONENT_ALIASES: dict[str, str] = {
    "odh-notebook-controller": "kubeflow",
    "kubeflow-notebook-controller": "kubeflow",
    "notebooks": "notebooks",
    "odh-model-controller": "odh-model-controller",
    "odh-elyra": "elyra",
    "codeflare-operator": "codeflare-operator",
    "codeflare-sdk": "codeflare-sdk",
    "model-registry-operator": "model-registry-operator",
    "trustyai-service-operator": "trustyai-service-operator",
    "trustyai-explainability": "trustyai-explainability",
    "modelmeshserving": "modelmesh-serving",
    "modelmesh": "modelmesh",
}

# ---------------------------------------------------------------------------
# Names that are not cloneable repos (teams, process areas, etc.)
# ---------------------------------------------------------------------------

NON_REPO_NAMES: set[str] = {
    "AI Core Platform",
    "AI Hub",
    "AI Platform DevOps",
    "AI Safety",
    "AgentDev",
    "Agentic",
    "AutoML",
    "CI/CD",
    "Customer Exploration & Test",
    "DAST pipeline",
    "DevOps",
    "DIH (Disconnected Install Helper)",
    "Docling",
    "Documentation",
    "IBM P",
    "IBM Z",
    "InfraOps",
    "Internal Processes & Documentation",
    "Model Runtimes",
    "Notebooks Extensions",
    "Notebooks Images",
    "Notebooks Server",
    "ODS-CI",
    "OpenShift AI Productization",
    "PLATFORM",
    "QE",
    "RAG + Vector DB",
    "Red Hat AI Python Index",
    "Report Portal / DataRouter",
    "SDG Hub",
    "Security",
    "TestOps",
    "Training Hub",
    "Workload Orchestration",
    "documentation",
    "jenkins",
    "platform",
}


def normalize_component_name(raw_name: str) -> str | None:
    """Normalize a context-map component name to a canonical repo name.

    Handles:
    - Parenthetical annotations: ``kubeflow (odh-notebook-controller)`` -> ``kubeflow``
    - Version suffixes: ``kubeflow (ODH Notebook Controller) - 2.x`` -> ``kubeflow``
    - Sub-package annotations: ``odh-dashboard (gen-ai package)`` -> ``odh-dashboard``
    - Known aliases: ``odh-notebook-controller`` -> ``kubeflow``
    - Non-repo names (teams, processes): returns None

    Returns the canonical downstream repo name, or None if not cloneable.
    """
    name = raw_name.strip()

    if not name:
        return None

    # Skip known non-repo names
    if name in NON_REPO_NAMES:
        return None

    # Strip parenthetical annotations: "kubeflow (odh-notebook-controller)" -> "kubeflow"
    name = re.sub(r"\s*\(.*?\)", "", name).strip()

    # Strip version/branch suffixes: "kubeflow - 2.x" -> "kubeflow"
    name = re.sub(r"\s*-\s*[\d][\d.x]*\s*(?:N-\d+)?$", "", name).strip()

    if not name:
        return None

    # Apply aliases
    if name in COMPONENT_ALIASES:
        name = COMPONENT_ALIASES[name]

    return name


def get_midstream(downstream_name: str) -> tuple[str, str] | None:
    """Return (org, repo) for the midstream equivalent, or None for downstream-only repos.

    Convention: ``opendatahub-io/{downstream_name}`` unless overridden
    by ``MIDSTREAM_EXCEPTIONS``.
    """
    if downstream_name in DOWNSTREAM_ONLY:
        return None

    if downstream_name in MIDSTREAM_EXCEPTIONS:
        return MIDSTREAM_EXCEPTIONS[downstream_name]

    return ("opendatahub-io", downstream_name)


def get_upstream(downstream_name: str) -> str | None:
    """Return ``org/repo`` of the true upstream if known, else None."""
    return KNOWN_UPSTREAMS.get(downstream_name)


def _repo_exists(org: str, repo: str) -> bool:
    """Check if a GitHub repo exists via a HEAD request (no auth required for public repos)."""
    url = f"https://github.com/{org}/{repo}"
    req = urllib.request.Request(url, method="HEAD")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status < 400
    except Exception:
        return False


def clone_midstream_repo(downstream_name: str, workspace_dir: Path) -> Path | None:
    """Clone the midstream repo into *workspace_dir* using the downstream name as the directory.

    Returns the clone path on success, or None on failure (e.g. repo
    doesn't exist).  Skips cloning if the directory already exists.
    Checks that the remote repo exists before attempting to clone.
    """
    midstream = get_midstream(downstream_name)
    if midstream is None:
        log.warning("No midstream repo for downstream-only component: %s", downstream_name)
        return None

    org, repo = midstream
    clone_dir = workspace_dir / downstream_name

    if clone_dir.exists():
        log.info("Clone already exists: %s", clone_dir)
        return clone_dir

    if not _repo_exists(org, repo):
        log.warning("Repo does not exist: https://github.com/%s/%s — skipping clone for %s",
                     org, repo, downstream_name)
        return None

    clone_url = f"https://github.com/{org}/{repo}.git"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    log.info("Cloning %s/%s -> %s", org, repo, clone_dir)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(clone_dir)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return clone_dir
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("Failed to clone %s/%s (%s): %s", org, repo, downstream_name, exc)
        return None
