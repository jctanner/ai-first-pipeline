#!/bin/bash
# Deploy Elasticsearch for trace indexing

set -euo pipefail

echo "==> Deploying Elasticsearch..."

kubectl apply -f /vagrant/deploy/k8s/17-elasticsearch.yaml

echo "  Waiting for Elasticsearch to be ready..."
kubectl wait --for=condition=Available --timeout=180s \
  deployment/elasticsearch -n ai-pipeline || true

SVC_IP=$(kubectl get svc -n ai-pipeline elasticsearch -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "pending")

echo "==> Elasticsearch deployed successfully"
echo ""
echo "Access Elasticsearch:"
echo "  - Internal: http://elasticsearch.ai-pipeline.svc.cluster.local:9200"
echo "  - ClusterIP: ${SVC_IP}:9200"
echo ""
echo "Elasticsearch is configured with:"
echo "  - Single-node discovery"
echo "  - Security disabled (cluster-internal only)"
echo "  - Storage: 20Gi PVC (elasticsearch-data)"
echo "  - Heap: 512m-1g"
echo ""
