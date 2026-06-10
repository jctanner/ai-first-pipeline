# Architecture-Context Corpus Generation

Extract benchmark questions from production trace data in Elasticsearch and build the corpus YAML.

Elasticsearch is cluster-internal only (ClusterIP in the `ai-pipeline` namespace), so these scripts must run inside a pod on the k3s cluster. The cluster runs inside a Vagrant VM.

## SSH into the Vagrant VM

```bash
cd /home/jtanner/workspace/github/jctanner.redhat/ai-first-pipeline
vagrant ssh
```

All `kubectl` commands below run inside the VM.

## Launch a Pod

Start a pod with access to Elasticsearch and the PVCs. The `pipeline-agent:latest` image is built locally (not in a registry), so `imagePullPolicy: Never` is required:

```bash
kubectl run corpus-extract -n ai-pipeline \
  --image=pipeline-agent:latest \
  --restart=Never \
  --image-pull-policy=Never \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "corpus-extract",
        "image": "pipeline-agent:latest",
        "imagePullPolicy": "Never",
        "command": ["sleep", "3600"],
        "env": [
          {"name": "ELASTICSEARCH_URI", "value": "http://elasticsearch:9200"}
        ],
        "volumeMounts": [
          {"name": "artifacts", "mountPath": "/app/artifacts"},
          {"name": "context", "mountPath": "/app/.context"}
        ]
      }],
      "volumes": [
        {"name": "artifacts", "persistentVolumeClaim": {"claimName": "pipeline-artifacts"}},
        {"name": "context", "persistentVolumeClaim": {"claimName": "pipeline-context"}}
      ]
    }
  }'
kubectl wait --for=condition=Ready pod/corpus-extract -n ai-pipeline --timeout=60s
```

## Copy extraction scripts into the pod

The extraction scripts are not in the container image. Copy them from the Vagrant shared directory (`/vagrant/`):

```bash
kubectl cp /vagrant/scripts/extract_corpus_tier4.py ai-pipeline/corpus-extract:/app/scripts/extract_corpus_tier4.py
kubectl cp /vagrant/scripts/extract_corpus_tier12.py ai-pipeline/corpus-extract:/app/scripts/extract_corpus_tier12.py
kubectl cp /vagrant/scripts/extract_corpus_tier3.py ai-pipeline/corpus-extract:/app/scripts/extract_corpus_tier3.py
kubectl cp /vagrant/scripts/build_corpus.py ai-pipeline/corpus-extract:/app/scripts/build_corpus.py
```

## Install the elasticsearch Python package

The container's venv doesn't include `elasticsearch`. Install it via `uv` (use v8.x to match the ES 8.17 server):

```bash
kubectl exec corpus-extract -n ai-pipeline -- bash -c 'cd /app && uv pip install "elasticsearch>=8,<9"'
```

## Steps

All steps below run via `kubectl exec`. Use single quotes for the outer `vagrant ssh -c` and escape `$ELASTICSEARCH_URI` as `\$ELASTICSEARCH_URI` if running from outside the VM.

### Step 1: Clone architecture-context (if not already on the PVC)

```bash
kubectl exec corpus-extract -n ai-pipeline -- bash -c '
if [ ! -d /app/.context/architecture-context/.git ]; then
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/opendatahub-io/architecture-context \
    /app/.context/architecture-context
  git -C /app/.context/architecture-context sparse-checkout set architecture
fi
'
```

### Step 2: Extract questions from Elasticsearch (3 scripts, can run in parallel)

```bash
kubectl exec corpus-extract -n ai-pipeline -- bash -c '
mkdir -p /app/artifacts/var/benchmarks/arch-context/raw

python scripts/extract_corpus_tier4.py \
  --elastic-uri $ELASTICSEARCH_URI \
  --output /app/artifacts/var/benchmarks/arch-context/raw/tier4-extracted.jsonl &

python scripts/extract_corpus_tier12.py \
  --elastic-uri $ELASTICSEARCH_URI \
  --output /app/artifacts/var/benchmarks/arch-context/raw/tier12-extracted.jsonl &

python scripts/extract_corpus_tier3.py \
  --elastic-uri $ELASTICSEARCH_URI \
  --output /app/artifacts/var/benchmarks/arch-context/raw/tier3-extracted.jsonl &

wait
'
```

Each writes a JSONL file into the artifacts PVC. Report the count of questions extracted per tier.

### Step 3: Build the corpus

```bash
kubectl exec corpus-extract -n ai-pipeline -- bash -c '
python scripts/build_corpus.py \
  --raw-dir /app/artifacts/var/benchmarks/arch-context/raw \
  --arch-context-dir /app/.context/architecture-context \
  --output /app/artifacts/var/benchmarks/arch-context/corpus.yaml
'
```

Report: total questions, per-tier counts, and how many need manual curation (`NEEDS_CURATION`).

### Step 4: Verify the output

Read `/app/artifacts/var/benchmarks/arch-context/corpus.yaml` and confirm:
- It has a `version`, `architecture_context_commit`, and `generated_date` header
- Questions have sequential IDs (`t1-001`, `t2-001`, etc.)
- `source_files` paths are populated (not empty lists)
- Report a summary: tier counts, answerable vs unanswerable split, how many have `source_excerpt` populated vs empty

Do NOT run the benchmark itself (`run_benchmark.py`) — this is extraction only.

### Step 5: Clean up

```bash
kubectl delete pod corpus-extract -n ai-pipeline
```
