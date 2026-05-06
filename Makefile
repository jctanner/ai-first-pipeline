# AI-First Pipeline Makefile
# Provides convenient targets for common development tasks
# Targets prefixed with "vagrant-" are designed to run from the host and execute inside Vagrant VM

.PHONY: help
help: ## Show this help message
	@echo "AI-First Pipeline - Available targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Common workflows (host mode):"
	@echo "  make rebuild-dashboard             # Rebuild dashboard after code changes"
	@echo "  make rebuild-agent                 # Rebuild agent image"
	@echo "  make rebuild-all                   # Rebuild all images"
	@echo "  make status                        # Check cluster status"
	@echo ""
	@echo "Vagrant mode: use vagrant-* prefixed targets (e.g. make vagrant-status)"

##@ Vagrant: Dashboard Management

vagrant-build-dashboard: ## Build dashboard image only (no redeploy)
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash 05a-build-dashboard.sh"

vagrant-rebuild-dashboard: ## Rebuild and redeploy dashboard (for dashboard/lib code changes)
	@echo "==> Rebuilding dashboard image..."
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash 05a-build-dashboard.sh"
	vagrant ssh -c "kubectl delete pod -n ai-pipeline -l app=pipeline-dashboard --wait=false"
	@echo "==> Waiting for dashboard pod to be ready..."
	vagrant ssh -c "kubectl wait --for=condition=ready pod -n ai-pipeline -l app=pipeline-dashboard --timeout=60s" || true
	@echo "✓ Dashboard rebuilt and redeployed"
	@echo "   Access at: https://dashboard.local"

vagrant-dashboard-logs: ## Follow dashboard logs
	vagrant ssh -c "kubectl logs -n ai-pipeline -l app=pipeline-dashboard -f"

##@ Vagrant: Agent Management

vagrant-build-agent: ## Build agent image only (no pod restart needed)
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash 05b-build-agent.sh"

vagrant-rebuild-agent: ## Rebuild agent image (has Claude CLI, used for K8s jobs)
	@echo "==> Building pipeline-agent image..."
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash 05b-build-agent.sh"
	@echo "✓ Agent image rebuilt and imported to k3s"
	@echo "   New jobs will use the updated image"

vagrant-agent-test: ## Run a test job with the agent image
	@echo "==> Testing agent image..."
	vagrant ssh -c "kubectl run test-agent --rm -i --restart=Never --image=pipeline-agent:latest -n ai-pipeline -- claude --version" || true

##@ Vagrant: Emulator Management

vagrant-rebuild-jira: ## Rebuild and redeploy Jira emulator
	@echo "==> Rebuilding Jira emulator..."
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash 05b-build-jira-emulator.sh"
	vagrant ssh -c "kubectl rollout restart deployment/jira-emulator -n ai-pipeline"
	vagrant ssh -c "kubectl rollout status deployment/jira-emulator -n ai-pipeline --timeout=60s"
	@echo "✓ Jira emulator rebuilt and redeployed"

vagrant-rebuild-github: ## Rebuild and redeploy GitHub emulator
	@echo "==> Rebuilding GitHub emulator..."
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash 05a-build-github-emulator.sh"
	vagrant ssh -c "kubectl rollout restart deployment/github-emulator -n ai-pipeline"
	vagrant ssh -c "kubectl rollout status deployment/github-emulator -n ai-pipeline --timeout=60s"
	@echo "✓ GitHub emulator rebuilt and redeployed"

##@ Vagrant: Full Stack Management

vagrant-build-all: ## Build dashboard and agent images only (no redeploy)
	@echo "==> Building dashboard and agent images..."
	@$(MAKE) vagrant-build-dashboard
	@$(MAKE) vagrant-build-agent
	@echo "✓ Dashboard and agent images built"

vagrant-rebuild-all: ## Rebuild and redeploy dashboard, rebuild agent
	@echo "==> Rebuilding dashboard and agent images..."
	@$(MAKE) vagrant-rebuild-dashboard
	@$(MAKE) vagrant-build-agent
	@echo "✓ Dashboard redeployed, agent image rebuilt"

vagrant-rebuild-all-with-emulators: ## Rebuild all images including emulators
	@echo "==> Rebuilding all images (dashboard, agent, emulators)..."
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash 05-build-images.sh"
	@echo "✓ All images rebuilt"

vagrant-deploy-all: ## Run full deployment from scratch
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash deploy-all.sh"

vagrant-restart-all: ## Restart all pipeline pods
	vagrant ssh -c "kubectl rollout restart deployment -n ai-pipeline"
	@echo "==> Waiting for rollouts to complete..."
	vagrant ssh -c "kubectl rollout status deployment --all -n ai-pipeline --timeout=120s"

##@ Vagrant: Status & Debugging

vagrant-status: ## Check cluster and pod status
	@echo "==> Cluster Status:"
	vagrant ssh -c "kubectl get nodes"
	@echo ""
	@echo "==> Pipeline Pods:"
	vagrant ssh -c "kubectl get pods -n ai-pipeline -o wide"
	@echo ""
	@echo "==> Pipeline Services:"
	vagrant ssh -c "kubectl get svc -n ai-pipeline"
	@echo ""
	@echo "==> Recent Jobs:"
	vagrant ssh -c "kubectl get jobs -n ai-pipeline --sort-by=.metadata.creationTimestamp | tail -10"

vagrant-images: ## List imported k3s images
	vagrant ssh -c "sudo k3s ctr images ls | grep -E 'ai-first-pipeline|pipeline-agent|github-emulator|jira-emulator|ingress-proxy'"

vagrant-logs-dashboard: vagrant-dashboard-logs ## Alias for vagrant-dashboard-logs

vagrant-logs-jira: ## Follow Jira emulator logs
	vagrant ssh -c "kubectl logs -n ai-pipeline -l app=jira-emulator -f"

vagrant-logs-github: ## Follow GitHub emulator logs
	vagrant ssh -c "kubectl logs -n ai-pipeline -l app=github-emulator -f"

vagrant-logs-mlflow: ## Follow MLflow logs
	vagrant ssh -c "kubectl logs -n ai-pipeline -l app=mlflow -f"

vagrant-logs-job: ## Follow last job logs (set JOB_NAME=<name> to specify)
	@if [ -z "$(JOB_NAME)" ]; then \
		echo "Finding most recent job..."; \
		JOB=$$(vagrant ssh -c "kubectl get jobs -n ai-pipeline --sort-by=.metadata.creationTimestamp -o name | tail -1"); \
		echo "Following logs for $$JOB"; \
		vagrant ssh -c "kubectl logs -n ai-pipeline $$JOB -f"; \
	else \
		vagrant ssh -c "kubectl logs -n ai-pipeline job/$(JOB_NAME) -f"; \
	fi

vagrant-describe-job: ## Describe last job (set JOB_NAME=<name> to specify)
	@if [ -z "$(JOB_NAME)" ]; then \
		JOB=$$(vagrant ssh -c "kubectl get jobs -n ai-pipeline --sort-by=.metadata.creationTimestamp -o name | tail -1"); \
		vagrant ssh -c "kubectl describe -n ai-pipeline $$JOB"; \
	else \
		vagrant ssh -c "kubectl describe -n ai-pipeline job/$(JOB_NAME)"; \
	fi

##@ Vagrant: Elasticsearch & Trace Sync

vagrant-deploy-elasticsearch: ## Deploy Elasticsearch to the cluster
	@echo "==> Deploying Elasticsearch..."
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash 11-deploy-elasticsearch.sh"

vagrant-sync-traces: ## Sync MLflow traces to Elasticsearch (incremental)
	@echo "==> Syncing MLflow traces to Elasticsearch..."
	vagrant ssh -c "kubectl exec -n ai-pipeline deploy/pipeline-dashboard -c dashboard -- uv run python /app/scripts/sync_mlflow_to_elastic.py"

vagrant-sync-traces-full: ## Full resync of all MLflow traces to Elasticsearch
	@echo "==> Full resync of MLflow traces to Elasticsearch..."
	vagrant ssh -c "kubectl exec -n ai-pipeline deploy/pipeline-dashboard -c dashboard -- uv run python /app/scripts/sync_mlflow_to_elastic.py --full"

vagrant-logs-elasticsearch: ## Follow Elasticsearch logs
	vagrant ssh -c "kubectl logs -n ai-pipeline -l app=elasticsearch -f"

##@ Vagrant: Markov Management

vagrant-markov-kill: ## Kill all running markov jobs and pods
	@echo "==> Deleting all markov jobs..."
	vagrant ssh -c "kubectl delete jobs -n ai-pipeline -l app=markov --wait=false 2>/dev/null" || true
	@echo "==> Deleting any orphaned markov pods..."
	vagrant ssh -c "kubectl delete pods -n ai-pipeline -l app=markov --wait=false 2>/dev/null" || true
	@echo "✓ All markov jobs and pods deleted"

vagrant-markov-status: ## Show markov run status
	vagrant ssh -c "kubectl get jobs -n ai-pipeline -l app=markov --sort-by=.metadata.creationTimestamp | tail -20"

vagrant-markov-logs: ## Follow markovd logs
	vagrant ssh -c "kubectl logs -n ai-pipeline -l app=markovd -f"

vagrant-rebuild-markovd: ## Rebuild and redeploy markovd
	@echo "==> Building markovd image..."
	vagrant ssh -c "cd /vagrant && bash deploy/scripts/05c-build-markovd.sh"
	@echo "==> Restarting markovd..."
	vagrant ssh -c "kubectl rollout restart deployment/markovd -n ai-pipeline"
	vagrant ssh -c "kubectl rollout status deployment/markovd -n ai-pipeline --timeout=60s"
	@echo "✓ markovd rebuilt and redeployed"

vagrant-rebuild-markov: ## Rebuild markov CLI binary
	@echo "==> Building markov CLI..."
	vagrant ssh -c "cd /vagrant && bash deploy/scripts/05d-build-markov.sh"
	@echo "✓ markov CLI rebuilt"

##@ Vagrant: Backup & Restore

vagrant-backup: ## Backup all service data to ./backups/<timestamp>/
	vagrant ssh -c "sudo bash /vagrant/deploy/scripts/backup.sh"

vagrant-backup-full: ## Backup all data including workspace and context PVCs
	vagrant ssh -c "sudo bash /vagrant/deploy/scripts/backup.sh --include-workspace --include-context"

vagrant-restore: ## Restore from backup (set BACKUP=<path>, e.g. BACKUP=/vagrant/backups/2026-05-01_143028)
	@if [ -z "$(BACKUP)" ]; then \
		echo "ERROR: Set BACKUP=<path> (e.g. make vagrant-restore BACKUP=/vagrant/backups/2026-05-01_143028)"; \
		echo "Run 'make vagrant-list-backups' to see available backups."; \
		exit 1; \
	fi
	vagrant ssh -c "sudo bash /vagrant/deploy/scripts/restore.sh $(BACKUP)"

vagrant-list-backups: ## List available backups
	vagrant ssh -c "bash /vagrant/deploy/scripts/list-backups.sh"

##@ Vagrant: Cleanup

vagrant-delete-jobs: ## Delete all completed/failed jobs
	vagrant ssh -c "kubectl delete jobs -n ai-pipeline --all"

vagrant-clean-images: ## Remove all local docker images (frees space)
	vagrant ssh -c "sudo docker system prune -af"

vagrant-reset: ## Delete namespace and reinstall (WARNING: destructive)
	@echo "WARNING: This will delete the ai-pipeline namespace and all resources!"
	@read -p "Are you sure? (yes/no): " confirm && [ "$$confirm" = "yes" ]
	vagrant ssh -c "kubectl delete namespace ai-pipeline || true"
	vagrant ssh -c "cd /vagrant/deploy/scripts && sudo bash deploy-all.sh"

##@ Host: K3s on Host (no Vagrant)
#
# These targets run k3s directly on the host machine.
# Deploy scripts use PROJECT_ROOT to find project files.

HOST_PROJECT_ROOT := $(shell pwd)

host-install-k3s: ## Install K3s on host with /data auto-detection
	sudo bash deploy/scripts/01-install-k3s-host.sh

host-deploy-all: ## Run full deployment from scratch on host
	sudo PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/deploy-all.sh

host-build-dashboard: ## Build dashboard image on host
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05a-build-dashboard.sh

host-rebuild-dashboard: ## Rebuild and redeploy dashboard on host
	@echo "==> Rebuilding dashboard image..."
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05a-build-dashboard.sh
	kubectl delete pod -n ai-pipeline -l app=pipeline-dashboard --wait=false
	@echo "==> Waiting for dashboard pod to be ready..."
	kubectl wait --for=condition=ready pod -n ai-pipeline -l app=pipeline-dashboard --timeout=60s || true
	@echo "✓ Dashboard rebuilt and redeployed"

host-build-agent: ## Build agent image on host
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05b-build-agent.sh

host-rebuild-agent: ## Rebuild agent image on host
	@echo "==> Building pipeline-agent image..."
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05b-build-agent.sh
	@echo "✓ Agent image rebuilt and imported to k3s"

host-agent-test: ## Run a test job with the agent image on host
	@echo "==> Testing agent image..."
	kubectl run test-agent --rm -i --restart=Never --image=pipeline-agent:latest -n ai-pipeline -- claude --version || true

host-rebuild-jira: ## Rebuild and redeploy Jira emulator on host
	@echo "==> Rebuilding Jira emulator..."
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05b-build-jira-emulator.sh
	kubectl rollout restart deployment/jira-emulator -n ai-pipeline
	kubectl rollout status deployment/jira-emulator -n ai-pipeline --timeout=60s
	@echo "✓ Jira emulator rebuilt and redeployed"

host-rebuild-github: ## Rebuild and redeploy GitHub emulator on host
	@echo "==> Rebuilding GitHub emulator..."
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05a-build-github-emulator.sh
	kubectl rollout restart deployment/github-emulator -n ai-pipeline
	kubectl rollout status deployment/github-emulator -n ai-pipeline --timeout=60s
	@echo "✓ GitHub emulator rebuilt and redeployed"

host-build-all: ## Build dashboard and agent images on host
	@echo "==> Building dashboard and agent images..."
	@$(MAKE) host-build-dashboard
	@$(MAKE) host-build-agent
	@echo "✓ Dashboard and agent images built"

host-rebuild-all: ## Rebuild and redeploy dashboard, rebuild agent on host
	@echo "==> Rebuilding dashboard and agent images..."
	@$(MAKE) host-rebuild-dashboard
	@$(MAKE) host-build-agent
	@echo "✓ Dashboard redeployed, agent image rebuilt"

host-rebuild-all-with-emulators: ## Rebuild all images including emulators on host
	@echo "==> Rebuilding all images..."
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05-build-images.sh
	@echo "✓ All images rebuilt"

host-restart-all: ## Restart all pipeline pods on host
	kubectl rollout restart deployment -n ai-pipeline
	@echo "==> Waiting for rollouts to complete..."
	kubectl rollout status deployment --all -n ai-pipeline --timeout=120s

host-status: ## Check cluster and pod status on host
	@echo "==> Cluster Status:"
	kubectl get nodes
	@echo ""
	@echo "==> Pipeline Pods:"
	kubectl get pods -n ai-pipeline -o wide
	@echo ""
	@echo "==> Pipeline Services:"
	kubectl get svc -n ai-pipeline
	@echo ""
	@echo "==> Recent Jobs:"
	kubectl get jobs -n ai-pipeline --sort-by=.metadata.creationTimestamp | tail -10

host-images: ## List imported k3s images on host
	sudo k3s ctr images ls | grep -E 'pipeline-agent|pipeline-dashboard|github-emulator|jira-emulator|ingress-proxy|markov' || true

host-logs-dashboard: ## Follow dashboard logs on host
	kubectl logs -n ai-pipeline -l app=pipeline-dashboard -f

host-logs-jira: ## Follow Jira emulator logs on host
	kubectl logs -n ai-pipeline -l app=jira-emulator -f

host-logs-github: ## Follow GitHub emulator logs on host
	kubectl logs -n ai-pipeline -l app=github-emulator -f

host-logs-mlflow: ## Follow MLflow logs on host
	kubectl logs -n ai-pipeline -l app=mlflow -f

host-logs-job: ## Follow last job logs on host (set JOB_NAME=<name> to specify)
	@if [ -z "$(JOB_NAME)" ]; then \
		echo "Finding most recent job..."; \
		JOB=$$(kubectl get jobs -n ai-pipeline --sort-by=.metadata.creationTimestamp -o name | tail -1); \
		echo "Following logs for $$JOB"; \
		kubectl logs -n ai-pipeline $$JOB -f; \
	else \
		kubectl logs -n ai-pipeline job/$(JOB_NAME) -f; \
	fi

host-describe-job: ## Describe last job on host (set JOB_NAME=<name> to specify)
	@if [ -z "$(JOB_NAME)" ]; then \
		JOB=$$(kubectl get jobs -n ai-pipeline --sort-by=.metadata.creationTimestamp -o name | tail -1); \
		kubectl describe -n ai-pipeline $$JOB; \
	else \
		kubectl describe -n ai-pipeline job/$(JOB_NAME); \
	fi

host-deploy-elasticsearch: ## Deploy Elasticsearch on host
	@echo "==> Deploying Elasticsearch..."
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/11-deploy-elasticsearch.sh

host-sync-traces: ## Sync MLflow traces to Elasticsearch on host (incremental)
	@echo "==> Syncing MLflow traces to Elasticsearch..."
	kubectl exec -n ai-pipeline deploy/pipeline-dashboard -c dashboard -- uv run python /app/scripts/sync_mlflow_to_elastic.py

host-sync-traces-full: ## Full resync of MLflow traces on host
	@echo "==> Full resync of MLflow traces to Elasticsearch..."
	kubectl exec -n ai-pipeline deploy/pipeline-dashboard -c dashboard -- uv run python /app/scripts/sync_mlflow_to_elastic.py --full

host-logs-elasticsearch: ## Follow Elasticsearch logs on host
	kubectl logs -n ai-pipeline -l app=elasticsearch -f

host-markov-kill: ## Kill all running markov jobs and pods on host
	@echo "==> Deleting all markov jobs..."
	kubectl delete jobs -n ai-pipeline -l app=markov --wait=false 2>/dev/null || true
	@echo "==> Deleting any orphaned markov pods..."
	kubectl delete pods -n ai-pipeline -l app=markov --wait=false 2>/dev/null || true
	@echo "✓ All markov jobs and pods deleted"

host-markov-status: ## Show markov run status on host
	kubectl get jobs -n ai-pipeline -l app=markov --sort-by=.metadata.creationTimestamp | tail -20

host-markov-logs: ## Follow markovd logs on host
	kubectl logs -n ai-pipeline -l app=markovd -f

host-deploy-markovd: ## Deploy markovd (first time) on host
	@echo "==> Deploying markovd..."
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05c-build-markovd.sh
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/12-deploy-markovd.sh
	@echo "✓ markovd deployed"

host-rebuild-markovd: ## Rebuild and redeploy markovd on host
	@echo "==> Building markovd image..."
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05c-build-markovd.sh
	@echo "==> Restarting markovd..."
	kubectl rollout restart deployment/markovd -n ai-pipeline
	kubectl rollout status deployment/markovd -n ai-pipeline --timeout=60s
	@echo "✓ markovd rebuilt and redeployed"

host-rebuild-markov: ## Rebuild markov CLI binary on host
	@echo "==> Building markov CLI..."
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/05d-build-markov.sh
	@echo "✓ markov CLI rebuilt"

host-backup: ## Backup all service data on host
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/backup.sh

host-backup-full: ## Backup all data including workspace and context on host
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/backup.sh --include-workspace --include-context

host-restore: ## Restore from backup on host (set BACKUP=<path>)
	@if [ -z "$(BACKUP)" ]; then \
		echo "ERROR: Set BACKUP=<path> (e.g. make host-restore BACKUP=backups/2026-05-01_143028)"; \
		echo "Run 'make host-list-backups' to see available backups."; \
		exit 1; \
	fi
	bash deploy/scripts/restore.sh $(BACKUP)

host-list-backups: ## List available backups on host
	PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/list-backups.sh

host-delete-jobs: ## Delete all completed/failed jobs on host
	kubectl delete jobs -n ai-pipeline --all

host-clean-images: ## Remove all local docker images on host (frees space)
	docker system prune -af

host-reset: ## Delete namespace and reinstall on host (WARNING: destructive)
	@echo "WARNING: This will delete the ai-pipeline namespace and all resources!"
	@read -p "Are you sure? (yes/no): " confirm && [ "$$confirm" = "yes" ]
	kubectl delete namespace ai-pipeline || true
	sudo PROJECT_ROOT=$(HOST_PROJECT_ROOT) bash deploy/scripts/deploy-all.sh

##@ Local Development (no Vagrant)

test: ## Run Python tests locally
	uv run pytest tests/ -v

lint: ## Run linters locally
	uv run ruff check lib/ scripts/
	uv run mypy lib/

format: ## Format code locally
	uv run ruff format lib/ scripts/

sync: ## Sync Python dependencies
	uv sync

install-gitleaks: ## Install gitleaks to ./bin
	@echo "==> Installing gitleaks to ./bin..."
	@mkdir -p bin
	@curl -sSL https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz | tar xz -C bin/
	@chmod +x bin/gitleaks
	@echo "✓ gitleaks installed to ./bin/gitleaks"

security: ## Run security scans (gitleaks)
	@echo "==> Running gitleaks to detect secrets..."
	@if [ -x ./bin/gitleaks ]; then \
		./bin/gitleaks detect --verbose; \
	elif command -v gitleaks &> /dev/null; then \
		gitleaks detect --verbose; \
	else \
		echo "ERROR: gitleaks not found"; \
		echo "Run: make install-gitleaks"; \
		exit 1; \
	fi
	@echo "✓ No secrets detected"

##@ Shortcuts (point to host-* targets; change to vagrant-* if using VM)

rebuild-dashboard: host-rebuild-dashboard ## Shortcut
rebuild-agent: host-rebuild-agent ## Shortcut
rebuild-markovd: host-rebuild-markovd ## Shortcut
rebuild-all: host-rebuild-all ## Shortcut
markov-kill: host-markov-kill ## Shortcut
status: host-status ## Shortcut
logs: host-logs-dashboard ## Shortcut
backup: host-backup ## Shortcut
backup-full: host-backup-full ## Shortcut
restore: host-restore ## Shortcut
list-backups: host-list-backups ## Shortcut
