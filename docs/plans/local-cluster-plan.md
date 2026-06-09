# Host-Mode K3s Setup

## Context

The k3s cluster currently runs inside a Vagrant VM (libvirt) with a 100GB virtual disk on the SSD. Containerd snapshots from benchmark job containers consume 52GB+, triggering k3s eviction and image GC that breaks running workloads. The host has a 1.9TB HDD at `/data` with 1.3TB free. Moving k3s to the host with `--data-dir /data/k3s` eliminates the disk constraint entirely.

Goal: Add `host-*` Makefile targets and host-compatible deploy scripts alongside the existing `vagrant-*` targets. Update shortcuts to point at host targets. The vagrant path remains fully functional.

## Approach

### 1. Parameterize deploy scripts (`/vagrant` → `$PROJECT_ROOT`)

Every build/deploy script hardcodes `cd /vagrant`. Add a `PROJECT_ROOT` variable at the top of each script that defaults to `/vagrant` for backward compatibility but can be overridden.

**Files to modify:**
- `deploy/scripts/05a-build-dashboard.sh` — `cd /vagrant` → `cd ${PROJECT_ROOT:-/vagrant}`
- `deploy/scripts/05b-build-agent.sh` — same
- `deploy/scripts/05a-build-github-emulator.sh` — same
- `deploy/scripts/05b-build-jira-emulator.sh` — same
- `deploy/scripts/05c-build-markovd.sh` — same
- `deploy/scripts/05d-build-markov.sh` — same
- `deploy/scripts/05-build-images.sh` — same
- `deploy/scripts/06-create-secrets.sh` — `/vagrant/.env` → `${PROJECT_ROOT:-/vagrant}/.env`
- `deploy/scripts/deploy-all.sh` — all `/vagrant/` references → `${PROJECT_ROOT:-/vagrant}/`
- `deploy/scripts/09-deploy-ingress-proxy.sh` — same
- `deploy/scripts/backup.sh` — same
- `deploy/scripts/restore.sh` — same

Pattern for each script — add near the top after `set -euo pipefail`:
```bash
PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"
```
Then replace all `/vagrant` with `${PROJECT_ROOT}`.

### 2. Create host k3s install script

**New file: `deploy/scripts/01-install-k3s-host.sh`**

Based on `01-install-k3s.sh` but:
- Auto-detects `/data` mount: if `/data` exists and is a mount point, uses `--data-dir /data/k3s`; otherwise omits `--data-dir` (k3s defaults to `/var/lib/rancher/k3s`)
- Uses `--tls-san 127.0.0.1` (no hardcoded VM IP)
- Sets up kubeconfig for current user (`$USER`) instead of `vagrant`
- Keeps `--disable traefik` (custom Go reverse proxy handles ingress)

```bash
K3S_FLAGS="--disable traefik --write-kubeconfig-mode 644 --tls-san 127.0.0.1 --node-name ai-pipeline-k3s"

if mountpoint -q /data 2>/dev/null; then
  echo "==> /data is a mount point, using /data/k3s for k3s storage"
  mkdir -p /data/k3s
  K3S_FLAGS="$K3S_FLAGS --data-dir /data/k3s"
else
  echo "==> /data not found, using default k3s storage"
fi

curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server $K3S_FLAGS" sh -
```

Kubeconfig setup:
```bash
mkdir -p $HOME/.kube
sudo cp /etc/rancher/k3s/k3s.yaml $HOME/.kube/config
sudo chown $USER:$USER $HOME/.kube/config
```

### 3. Add `host-*` targets to Makefile

Add a parallel set of targets. Instead of `vagrant ssh -c "..."`, run commands directly with `sudo` where needed. Set `PROJECT_ROOT` to the actual project directory.

Structure:
```makefile
# Common variable for host mode
HOST_PROJECT_ROOT := $(shell pwd)

##@ Host: Dashboard Management
host-build-dashboard:
	cd deploy/scripts && sudo PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash 05a-build-dashboard.sh

host-rebuild-dashboard:
	cd deploy/scripts && sudo PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash 05a-build-dashboard.sh
	kubectl delete pod -n ai-pipeline -l app=pipeline-dashboard --wait=false
	kubectl wait --for=condition=ready pod -n ai-pipeline -l app=pipeline-dashboard --timeout=60s || true
```

Full target list (mirrors vagrant targets):
- `host-build-dashboard` / `host-rebuild-dashboard`
- `host-build-agent` / `host-rebuild-agent`
- `host-agent-test`
- `host-rebuild-jira` / `host-rebuild-github`
- `host-build-all` / `host-rebuild-all` / `host-rebuild-all-with-emulators`
- `host-deploy-all`
- `host-restart-all`
- `host-status`
- `host-images`
- `host-logs-dashboard` / `host-logs-jira` / `host-logs-github` / `host-logs-mlflow` / `host-logs-job`
- `host-describe-job`
- `host-deploy-elasticsearch` / `host-sync-traces` / `host-sync-traces-full` / `host-logs-elasticsearch`
- `host-markov-kill` / `host-markov-status` / `host-markov-logs`
- `host-rebuild-markovd` / `host-rebuild-markov`
- `host-backup` / `host-backup-full` / `host-restore` / `host-list-backups`
- `host-delete-jobs` / `host-clean-images` / `host-reset`

### 4. Update shortcuts to point to host targets

```makefile
##@ Shortcuts (host mode)
rebuild-dashboard: host-rebuild-dashboard
rebuild-agent: host-rebuild-agent
...
```

### 5. Update `/etc/hosts`

Change `*.local` entries from VM IP to `127.0.0.1`:
```
127.0.0.1  mlflow.local jira.local github.local dashboard.local markovd.local
```

### 6. Update `scripts/clean-benchmark.sh`

Add host-mode support: when not in vagrant, run kubectl/curl directly instead of through `vagrant ssh -c`. Use `make host-markov-kill` instead of `make vagrant-markov-kill`.

## Execution Order

1. Parameterize all deploy scripts (`PROJECT_ROOT`)
2. Create `deploy/scripts/01-install-k3s-host.sh`
3. Add all `host-*` targets to Makefile, update shortcuts
4. Update `clean-benchmark.sh` for host mode
5. Install k3s on host: `sudo bash deploy/scripts/01-install-k3s-host.sh`
6. Update `/etc/hosts` to point `*.local` → `127.0.0.1`
7. Deploy: `make host-deploy-all`

## Verification

- `make host-status` — nodes ready, pods running
- `curl -sk https://dashboard.local` — dashboard responds
- `curl -sk https://mlflow.local/api/2.0/mlflow/experiments/search -X POST -H 'Content-Type: application/json' -d '{"max_results":10}'` — MLflow responds
- `make host-build-agent` — image builds and imports without vagrant
- `make host-agent-test` — agent pod runs successfully
