#!/usr/bin/env python3
"""Test K8s orchestrator."""

from lib.k8s_orchestrator import PipelineOrchestrator

# Initialize orchestrator
print("Initializing orchestrator...")
orchestrator = PipelineOrchestrator()

print(f"Connected to K8s (in_cluster={orchestrator.in_cluster})")
print(f"Namespace: {orchestrator.namespace}")

# List existing jobs
print("\nListing existing pipeline jobs...")
jobs = orchestrator.list_jobs()
print(f"Found {len(jobs)} jobs:")
for job in jobs:
    status = orchestrator._get_job_status(job)
    print(f"  - {job.metadata.name}: {status}")

print("\n✓ Orchestrator working!")
