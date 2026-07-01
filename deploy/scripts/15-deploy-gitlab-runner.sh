#!/bin/bash
# Deploy an in-cluster GitLab Runner (Kubernetes executor) that polls
# the gitlab-emulator coordinator and creates CI job pods.

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"

RUNNER_NAME="${RUNNER_NAME:-glemu-k8s-runner}"
RUNNER_TAGS="${RUNNER_TAGS:-k8s-incluster,aipcc-small-x86_64}"
RUNNER_IMAGE="${RUNNER_IMAGE:-alpine:3.20}"
RUNNER_MANAGER_IMAGE="${RUNNER_MANAGER_IMAGE:-gitlab/gitlab-runner:v19.1.1}"
RUNNER_NAMESPACE="${RUNNER_NAMESPACE:-gitlab-runner}"
REGISTRATION_TOKEN="${REGISTRATION_TOKEN:-runner-registration-token}"
EMULATOR_URL="https://gitlab-emulator.ai-pipeline.svc.cluster.local"

echo "==> Deploying GitLab Runner (in-cluster Kubernetes executor)..."

# Step 1: Apply RBAC
echo "--- Creating namespace and RBAC ---"
kubectl apply -f "${PROJECT_ROOT}/deploy/k8s/21-gitlab-runner.yaml"

# Step 2: Wait for gitlab-emulator to be ready
echo "--- Waiting for gitlab-emulator to be ready ---"
kubectl wait --for=condition=Available --timeout=120s \
  deployment/gitlab-emulator -n ai-pipeline || {
  echo "ERROR: gitlab-emulator deployment not ready"
  exit 1
}

for i in $(seq 1 15); do
  if kubectl exec -n ai-pipeline deployment/gitlab-emulator -- \
    python3 -c "import httpx; httpx.get('http://127.0.0.1:8000/api/v4').raise_for_status()" 2>/dev/null; then
    echo "  gitlab-emulator API is responding"
    break
  fi
  echo "  Waiting for gitlab-emulator API... ($i/15)"
  sleep 4
done

# Step 3: Register runner via emulator API
echo "--- Registering runner with emulator ---"
RUNNER_TOKEN=$(kubectl exec -n ai-pipeline deployment/gitlab-emulator -- \
  python3 -c "
import httpx, json, sys
try:
    r = httpx.post('http://127.0.0.1:8000/api/v4/runners', json={
        'token': '${REGISTRATION_TOKEN}',
        'description': '${RUNNER_NAME}',
        'tag_list': '${RUNNER_TAGS}',
        'run_untagged': False,
        'locked': False
    })
    r.raise_for_status()
    print(r.json()['token'])
except Exception as e:
    print(f'Registration failed: {e}', file=sys.stderr)
    sys.exit(1)
")

if [ -z "$RUNNER_TOKEN" ]; then
  echo "ERROR: Failed to register runner — no token received"
  exit 1
fi
echo "  Runner registered, token: ${RUNNER_TOKEN:0:12}..."

# Step 4: Extract CA certificate
echo "--- Extracting CA certificate ---"
CA_CERT=$(kubectl get configmap internal-ca-cert \
  -n ai-pipeline \
  -o jsonpath='{.data.ca\.crt}' 2>/dev/null || true)

if [ -z "$CA_CERT" ]; then
  echo "WARNING: Could not extract CA cert from ConfigMap"
  echo "  Runner may fail TLS verification"
fi

# Step 5: Build config.toml
echo "--- Building runner config ---"
CONFIG_TOML=$(cat <<EOF
concurrent = 4
check_interval = 3

[[runners]]
  name = "${RUNNER_NAME}"
  url = "${EMULATOR_URL}"
  token = "${RUNNER_TOKEN}"
  tls-ca-file = "/etc/gitlab-runner/certs/ca.crt"
  executor = "kubernetes"
  environment = ["GIT_SSL_CAINFO=/etc/gitlab-runner/certs/ca.crt"]

  [runners.kubernetes]
    namespace = "${RUNNER_NAMESPACE}"
    image = "${RUNNER_IMAGE}"
    poll_timeout = 180
    service_account = "gitlab-runner"

    [[runners.kubernetes.volumes.secret]]
      name = "gitlab-runner-ca"
      mount_path = "/etc/gitlab-runner/certs"
      read_only = true
EOF
)

# Step 6: Create ConfigMap and Secret
echo "--- Creating runner config and CA secret ---"
kubectl -n "${RUNNER_NAMESPACE}" delete configmap gitlab-runner-config --ignore-not-found
kubectl -n "${RUNNER_NAMESPACE}" create configmap gitlab-runner-config \
  --from-literal=config.toml="${CONFIG_TOML}"

kubectl -n "${RUNNER_NAMESPACE}" delete secret gitlab-runner-ca --ignore-not-found
if [ -n "$CA_CERT" ]; then
  kubectl -n "${RUNNER_NAMESPACE}" create secret generic gitlab-runner-ca \
    --from-literal=ca.crt="${CA_CERT}"
else
  kubectl -n "${RUNNER_NAMESPACE}" create secret generic gitlab-runner-ca \
    --from-literal=ca.crt=""
fi

# Step 7: Deploy runner manager
echo "--- Deploying runner manager ---"
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gitlab-runner
  namespace: ${RUNNER_NAMESPACE}
  labels:
    app: gitlab-runner
spec:
  replicas: 1
  selector:
    matchLabels:
      app: gitlab-runner
  template:
    metadata:
      labels:
        app: gitlab-runner
    spec:
      serviceAccountName: gitlab-runner
      containers:
        - name: gitlab-runner
          image: ${RUNNER_MANAGER_IMAGE}
          imagePullPolicy: IfNotPresent
          command: ["gitlab-runner"]
          args:
            - run
            - --working-directory=/home/gitlab-runner
            - --config=/etc/gitlab-runner/config.toml
            - --service=gitlab-runner
            - --user=gitlab-runner
          volumeMounts:
            - name: runner-config
              mountPath: /etc/gitlab-runner/config.toml
              subPath: config.toml
              readOnly: true
            - name: runner-ca
              mountPath: /etc/gitlab-runner/certs
              readOnly: true
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "500m"
      volumes:
        - name: runner-config
          configMap:
            name: gitlab-runner-config
        - name: runner-ca
          secret:
            secretName: gitlab-runner-ca
EOF

# Step 8: Wait for deployment
echo "--- Waiting for runner manager to be ready ---"
kubectl rollout status deployment/gitlab-runner \
  -n "${RUNNER_NAMESPACE}" --timeout=120s || true

echo ""
echo "==> GitLab Runner deployed successfully"
echo ""
echo "Runner details:"
echo "  Name:       ${RUNNER_NAME}"
echo "  Tags:       ${RUNNER_TAGS}"
echo "  Namespace:  ${RUNNER_NAMESPACE}"
echo "  Executor:   kubernetes"
echo "  Job image:  ${RUNNER_IMAGE}"
echo "  Manager:    ${RUNNER_MANAGER_IMAGE}"
echo ""
echo "Check status:"
echo "  kubectl get pods -n ${RUNNER_NAMESPACE}"
echo "  kubectl logs -n ${RUNNER_NAMESPACE} -l app=gitlab-runner"
echo ""
echo "Verify runner is registered:"
echo "  curl -sk ${EMULATOR_URL}/api/v4/runners"
echo "  Visit https://gitlab.local/admin/runners"
