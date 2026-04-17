# AI-First Pipeline Makefile
# Provides convenient targets for common development tasks
# Targets prefixed with "vagrant-" are designed to run from the host and execute inside Vagrant VM

.PHONY: help
help: ## Show this help message
	@echo "AI-First Pipeline - Available targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Common workflows:"
	@echo "  make vagrant-rebuild-dashboard    # Rebuild dashboard after code changes"
	@echo "  make vagrant-rebuild-agent         # Rebuild agent after adding Claude CLI"
	@echo "  make vagrant-rebuild-all           # Rebuild all images"
	@echo "  make vagrant-status                # Check cluster status"

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

vagrant-rebuild-all: ## Rebuild dashboard and agent images
	@echo "==> Rebuilding dashboard and agent images..."
	@$(MAKE) vagrant-build-dashboard
	@$(MAKE) vagrant-build-agent
	@echo "✓ Dashboard and agent images rebuilt"

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

##@ Shortcuts

rebuild-dashboard: vagrant-rebuild-dashboard ## Shortcut
rebuild-agent: vagrant-rebuild-agent ## Shortcut
rebuild-all: vagrant-rebuild-all ## Shortcut
status: vagrant-status ## Shortcut
logs: vagrant-logs-dashboard ## Shortcut
