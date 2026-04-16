# AI-First Pipeline K3s Troubleshooting Guide

Comprehensive troubleshooting guide for the K3s deployment of ai-first-pipeline.

## Table of Contents

- [K3s Issues](#k3s-issues)
- [cert-manager Issues](#cert-manager-issues)
- [Certificate Issues](#certificate-issues)
- [Application Deployment Issues](#application-deployment-issues)
- [Networking Issues](#networking-issues)
- [Storage Issues](#storage-issues)
- [Secret and Configuration Issues](#secret-and-configuration-issues)
- [Image Issues](#image-issues)
- [GitHub Emulator Issues](#github-emulator-issues)
- [Pipeline Dashboard Issues](#pipeline-dashboard-issues)
- [General Debugging](#general-debugging)

---

## K3s Issues

### Problem: K3s installation fails or times out

**Symptoms:**
```
Job for k3s.service failed because a timeout was exceeded.
```

**Diagnosis:**
```bash
# Check k3s service status
sudo systemctl status k3s

# Check k3s logs
sudo journalctl -u k3s -f

# Check for port conflicts
sudo netstat -tulpn | grep -E ':(6443|10250)'
```

**Solutions:**

1. **Clean previous installation:**
   ```bash
   sudo /usr/local/bin/k3s-uninstall.sh || true
   cd /vagrant/deploy/scripts
   sudo bash 01-install-k3s.sh
   ```

2. **Check system resources:**
   ```bash
   free -h  # At least 4GB RAM recommended
   df -h    # At least 10GB free disk space
   ```

3. **Disable conflicting services:**
   ```bash
   sudo systemctl stop docker containerd
   sudo systemctl disable docker containerd
   ```

### Problem: kubectl commands fail with "connection refused"

**Symptoms:**
```
The connection to the server localhost:8080 was refused
```

**Diagnosis:**
```bash
# Check if KUBECONFIG is set
echo $KUBECONFIG

# Check if kubeconfig exists
ls -la ~/.kube/config

# Check k3s is running
sudo systemctl is-active k3s
```

**Solutions:**
```bash
# Set KUBECONFIG
export KUBECONFIG=/home/vagrant/.kube/config

# Or copy from k3s default location
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
chmod 600 ~/.kube/config

# Add to bashrc
echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
source ~/.bashrc
```

### Problem: Nodes show "NotReady"

**Diagnosis:**
```bash
kubectl get nodes
kubectl describe node ai-pipeline-k3s
```

**Common causes:**
- CNI plugin not ready
- Insufficient disk space
- Kubelet not running

**Solutions:**
```bash
# Check kubelet logs
sudo journalctl -u k3s -n 100

# Restart k3s
sudo systemctl restart k3s

# Wait for node to be ready
kubectl wait --for=condition=Ready nodes --all --timeout=300s
```

---

## cert-manager Issues

### Problem: cert-manager pods not starting

**Diagnosis:**
```bash
kubectl get pods -n cert-manager
kubectl describe pod -n cert-manager <pod-name>
kubectl logs -n cert-manager deployment/cert-manager
```

**Common causes:**
- Insufficient resources
- Image pull issues
- CRD conflicts

**Solutions:**

1. **Check node resources:**
   ```bash
   kubectl describe nodes
   kubectl top nodes  # If metrics-server is available
   ```

2. **Reinstall cert-manager:**
   ```bash
   kubectl delete namespace cert-manager
   kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.4/cert-manager.yaml
   sleep 30
   cd /vagrant/deploy/scripts
   sudo bash 02-install-cert-manager.sh
   ```

3. **Check webhook connectivity:**
   ```bash
   kubectl get endpoints -n cert-manager
   kubectl logs -n cert-manager deployment/cert-manager-webhook
   ```

### Problem: cert-manager webhook timeouts

**Symptoms:**
```
Error from server (InternalError): error when creating "certificate.yaml": 
Internal error occurred: failed calling webhook
```

**Diagnosis:**
```bash
# Check webhook service
kubectl get svc -n cert-manager cert-manager-webhook

# Check webhook pod
kubectl get pods -n cert-manager -l app=webhook
```

**Solutions:**
```bash
# Delete and recreate webhook
kubectl delete pod -n cert-manager -l app=webhook

# Wait for webhook to be ready
kubectl wait --for=condition=Ready pod -n cert-manager -l app=webhook --timeout=120s
```

---

## Certificate Issues

### Problem: Certificate stuck in "Pending" or "False" state

**Symptoms:**
```bash
kubectl get certificate -n ai-pipeline
NAME                     READY   SECRET                   AGE
github-emulator-tls      False   github-emulator-tls      5m
```

**Diagnosis:**
```bash
# Check certificate details
kubectl describe certificate github-emulator-tls -n ai-pipeline

# Check certificate request
kubectl get certificaterequest -n ai-pipeline
kubectl describe certificaterequest -n ai-pipeline <name>

# Check issuer status
kubectl get clusterissuer internal-ca-issuer -o yaml
kubectl describe clusterissuer internal-ca-issuer
```

**Common issues:**

1. **Issuer not ready**
   ```bash
   # Wait for CA certificate to be issued first
   kubectl get certificate internal-ca -n ai-pipeline
   kubectl wait --for=condition=Ready certificate/internal-ca -n ai-pipeline --timeout=120s
   ```

2. **Wrong issuer reference**
   ```bash
   # Verify issuer exists
   kubectl get clusterissuer internal-ca-issuer
   
   # Check certificate spec
   kubectl get certificate github-emulator-tls -n ai-pipeline -o yaml | grep -A3 issuerRef
   ```

3. **Missing CA secret**
   ```bash
   # Verify CA secret exists
   kubectl get secret internal-ca-secret -n ai-pipeline
   
   # If missing, recreate CA infrastructure
   kubectl delete -f /vagrant/deploy/k8s/01-ca-issuer.yaml
   kubectl apply -f /vagrant/deploy/k8s/01-ca-issuer.yaml
   ```

**Solutions:**
```bash
# Delete and recreate certificate
kubectl delete certificate github-emulator-tls -n ai-pipeline
kubectl apply -f /vagrant/deploy/k8s/02-certificates.yaml

# Force renewal
kubectl delete secret github-emulator-tls -n ai-pipeline
# cert-manager will automatically recreate it
```

### Problem: x509: certificate signed by unknown authority

**Symptoms:**
```
curl: (60) SSL certificate problem: unable to get local issuer certificate
```

**Diagnosis:**
```bash
# Test from within cluster
kubectl run -it --rm debug --image=alpine --restart=Never -n ai-pipeline -- \
  sh -c "apk add curl && curl -v https://github-emulator.ai-pipeline.svc.cluster.local/"

# Check if CA ConfigMap exists
kubectl get configmap internal-ca-cert -n ai-pipeline -o yaml
```

**Solutions:**

1. **Recreate CA ConfigMap:**
   ```bash
   cd /vagrant/deploy/scripts
   sudo bash 04-extract-ca-cert.sh
   ```

2. **Verify CA cert in ConfigMap:**
   ```bash
   kubectl get configmap internal-ca-cert -n ai-pipeline -o jsonpath='{.data.ca\.crt}' | \
     openssl x509 -noout -text
   ```

3. **Restart pods to pick up new CA:**
   ```bash
   kubectl rollout restart deployment/pipeline-dashboard -n ai-pipeline
   kubectl rollout restart deployment/github-emulator -n ai-pipeline
   ```

### Problem: Certificate hostname mismatch

**Symptoms:**
```
curl: (51) SSL: certificate subject name does not match target host name
```

**Diagnosis:**
```bash
# Extract and examine certificate SANs
kubectl get secret github-emulator-tls -n ai-pipeline -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -text | grep -A1 "Subject Alternative Name"
```

**Expected output:**
```
DNS:github-emulator, DNS:github-emulator.ai-pipeline, 
DNS:github-emulator.ai-pipeline.svc, DNS:github-emulator.ai-pipeline.svc.cluster.local
```

**Solutions:**
```bash
# Edit certificate to add missing SANs
kubectl edit certificate github-emulator-tls -n ai-pipeline

# Or delete and recreate
kubectl delete certificate github-emulator-tls -n ai-pipeline
kubectl apply -f /vagrant/deploy/k8s/02-certificates.yaml
```

---

## Application Deployment Issues

### Problem: Pods stuck in "Pending"

**Diagnosis:**
```bash
kubectl get pods -n ai-pipeline
kubectl describe pod <pod-name> -n ai-pipeline
```

**Common causes:**

1. **PVC not bound**
   ```bash
   kubectl get pvc -n ai-pipeline
   # If Pending, check:
   kubectl describe pvc <pvc-name> -n ai-pipeline
   ```

2. **Insufficient node resources**
   ```bash
   kubectl describe nodes
   # Look for "Insufficient cpu" or "Insufficient memory"
   ```

3. **Image pull issues**
   ```bash
   kubectl describe pod <pod-name> -n ai-pipeline | grep -A5 Events
   # Look for "ImagePullBackOff" or "ErrImagePull"
   ```

**Solutions:**
```bash
# For PVC issues
kubectl delete pvc <pvc-name> -n ai-pipeline
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml

# For resource issues
kubectl edit deployment <deployment-name> -n ai-pipeline
# Reduce resource requests

# For image issues
cd /vagrant/deploy/scripts
sudo bash 05-build-images.sh
```

### Problem: Pods CrashLoopBackOff

**Diagnosis:**
```bash
kubectl logs <pod-name> -n ai-pipeline
kubectl logs <pod-name> -n ai-pipeline --previous  # Previous instance
kubectl describe pod <pod-name> -n ai-pipeline
```

**Common causes:**

1. **Missing environment variables**
   ```bash
   kubectl exec <pod-name> -n ai-pipeline -- env
   ```

2. **Missing secrets**
   ```bash
   kubectl get secrets -n ai-pipeline
   ```

3. **Application errors**
   ```bash
   kubectl logs <pod-name> -n ai-pipeline | tail -50
   ```

**Solutions:**
```bash
# Recreate secrets
cd /vagrant/deploy/scripts
sudo bash 06-create-secrets.sh

# Check pod environment
kubectl get pod <pod-name> -n ai-pipeline -o yaml | grep -A20 env:

# Exec into pod to debug
kubectl exec -it <pod-name> -n ai-pipeline -- /bin/bash
```

### Problem: Init container failures

**Diagnosis:**
```bash
kubectl describe pod <pod-name> -n ai-pipeline
kubectl logs <pod-name> -n ai-pipeline -c <init-container-name>
```

**Common init containers:**
- `update-ca-trust`: Updates CA certificates
- `setup-ca-trust`: Prepares CA cert for sharing

**Solutions:**
```bash
# Check if CA ConfigMap exists
kubectl get configmap internal-ca-cert -n ai-pipeline

# Recreate CA ConfigMap
cd /vagrant/deploy/scripts
sudo bash 04-extract-ca-cert.sh

# Delete pod to retry
kubectl delete pod <pod-name> -n ai-pipeline
```

---

## Networking Issues

### Problem: Service DNS doesn't resolve

**Symptoms:**
```
nslookup: can't resolve 'github-emulator.ai-pipeline.svc.cluster.local'
```

**Diagnosis:**
```bash
# Check service exists
kubectl get svc -n ai-pipeline

# Check CoreDNS is running
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Test DNS from a pod
kubectl run -it --rm debug --image=alpine --restart=Never -- \
  nslookup github-emulator.ai-pipeline.svc.cluster.local
```

**Solutions:**
```bash
# Restart CoreDNS
kubectl rollout restart deployment/coredns -n kube-system

# Check CoreDNS logs
kubectl logs -n kube-system -l k8s-app=kube-dns

# Verify service has endpoints
kubectl get endpoints -n ai-pipeline
```

### Problem: LoadBalancer IP stuck in "Pending"

**Diagnosis:**
```bash
kubectl get svc -n ai-pipeline
# EXTERNAL-IP shows <pending>
```

**Solutions:**
```bash
# Check servicelb is running
kubectl get pods -n kube-system -l app=svclb-pipeline-dashboard

# Check node IP
kubectl get nodes -o wide

# servicelb should assign node IP
# Wait a few minutes, then check again
kubectl get svc -n ai-pipeline -w
```

### Problem: Cannot access service from host

**Diagnosis:**
```bash
# Get LoadBalancer IP
kubectl get svc -n ai-pipeline

# Test from VM
curl http://<EXTERNAL-IP>:5000

# Test from host
curl http://192.168.56.10:5000
```

**Solutions:**

1. **Check port forwarding in Vagrantfile:**
   ```ruby
   config.vm.network "forwarded_port", guest: 5000, host: 5000
   ```

2. **Use VM IP directly:**
   ```bash
   # From host
   curl http://192.168.56.10:5000
   ```

3. **SSH port forwarding:**
   ```bash
   # From host
   vagrant ssh -- -L 5000:localhost:5000
   ```

---

## Storage Issues

### Problem: PVC stuck in "Pending"

**Diagnosis:**
```bash
kubectl get pvc -n ai-pipeline
kubectl describe pvc <pvc-name> -n ai-pipeline
```

**Common causes:**
- StorageClass not found
- Provisioner not running
- Insufficient disk space

**Solutions:**
```bash
# Check StorageClass
kubectl get storageclass

# Check local-path-provisioner
kubectl get pods -n kube-system -l app=local-path-provisioner

# Check node disk space
df -h

# Delete and recreate PVC
kubectl delete pvc <pvc-name> -n ai-pipeline
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml
```

### Problem: Volume mount permission errors

**Symptoms:**
```
Error: failed to create fsnotify watcher: too many open files
Permission denied: '/app/issues'
```

**Solutions:**
```bash
# Exec into pod and check permissions
kubectl exec -it <pod-name> -n ai-pipeline -- ls -la /app/

# Fix ownership in init container or deployment spec
# Add initContainer:
initContainers:
- name: fix-permissions
  image: busybox
  command: ['sh', '-c', 'chown -R 1000:1000 /app']
  volumeMounts:
  - name: data
    mountPath: /app
```

---

## Secret and Configuration Issues

### Problem: Secrets not found

**Diagnosis:**
```bash
kubectl get secrets -n ai-pipeline
kubectl describe pod <pod-name> -n ai-pipeline | grep -A5 "Secret"
```

**Solutions:**
```bash
# Ensure .env file exists
ls -la /vagrant/.env

# Recreate secrets
cd /vagrant/deploy/scripts
sudo bash 06-create-secrets.sh

# Verify secret was created
kubectl get secret pipeline-secrets -n ai-pipeline -o yaml
```

### Problem: Missing GCP credentials

**Symptoms:**
```
Error: Could not find google application credentials
```

**Solutions:**
```bash
# Check if GOOGLE_APPLICATION_CREDENTIALS is set in .env
grep GOOGLE_APPLICATION_CREDENTIALS /vagrant/.env

# Verify file exists
ls -la <path-from-env>

# Recreate secret
cd /vagrant/deploy/scripts
sudo bash 06-create-secrets.sh

# Verify mount in pod
kubectl exec <pod-name> -n ai-pipeline -- ls -la /secrets/gcp/
```

### Problem: Invalid Jira credentials

**Symptoms:**
```
Error: 401 Unauthorized from Jira API
```

**Solutions:**
```bash
# Test credentials from pod
kubectl exec -it deployment/pipeline-dashboard -n ai-pipeline -- bash

# Inside pod:
curl -u "$JIRA_USER:$JIRA_TOKEN" "$JIRA_SERVER/rest/api/2/myself"

# If fails, update .env and recreate secrets
```

---

## Image Issues

### Problem: ImagePullBackOff or ErrImagePull

**Diagnosis:**
```bash
kubectl describe pod <pod-name> -n ai-pipeline
# Look for "Failed to pull image"
```

**Solutions:**
```bash
# Check if image exists in k3s
sudo k3s ctr images ls | grep -E 'ai-first-pipeline|github-emulator'

# Rebuild and import
cd /vagrant/deploy/scripts
sudo bash 05-build-images.sh

# Verify image was imported
sudo k3s ctr images ls
```

### Problem: Image build fails

**Diagnosis:**
```bash
cd /vagrant/deploy/scripts
sudo bash 05-build-images.sh
# Check error messages
```

**Common issues:**

1. **Docker not installed:**
   ```bash
   sudo apt-get update
   sudo apt-get install -y docker.io
   ```

2. **Insufficient disk space:**
   ```bash
   df -h
   docker system prune -a  # Clean up old images
   ```

3. **Missing Dockerfile:**
   ```bash
   ls -la /vagrant/Dockerfile
   # Script creates a default one if missing
   ```

**Solutions:**
```bash
# Build manually
cd /vagrant
docker build -t ai-first-pipeline:latest .

# Import to k3s
docker save ai-first-pipeline:latest | sudo k3s ctr images import -
```

---

## GitHub Emulator Issues

### Problem: GitHub emulator not starting

**Diagnosis:**
```bash
kubectl logs -n ai-pipeline deployment/github-emulator
kubectl describe pod -n ai-pipeline -l app=github-emulator
```

**Common causes:**
- Image not built/imported
- Wrong port configuration
- TLS cert not mounted

**Solutions:**
```bash
# Check if image exists
sudo k3s ctr images ls | grep github-emulator

# Check certificate mount
kubectl exec deployment/github-emulator -n ai-pipeline -- ls -la /etc/tls/

# Rebuild emulator image
# First, clone the repo
cd /vagrant/.context
git clone https://github.com/jctanner/github-emulator.git
cd github-emulator
docker build -t github-emulator:latest .
docker save github-emulator:latest | sudo k3s ctr images import -
```

### Problem: Emulator not using cert-manager certificate

**Diagnosis:**
```bash
# Check what cert the emulator is serving
kubectl exec deployment/github-emulator -n ai-pipeline -- \
  openssl s_client -connect localhost:3000 -showcerts </dev/null 2>&1 | \
  openssl x509 -noout -issuer -subject
```

**Solutions:**
```bash
# Verify environment variables
kubectl get deployment github-emulator -n ai-pipeline -o yaml | grep -A10 env:

# Check if emulator code respects TLS_CERT_FILE and TLS_KEY_FILE
# May need to modify emulator code or deployment
```

---

## Pipeline Dashboard Issues

### Problem: Dashboard returns 500 errors

**Diagnosis:**
```bash
kubectl logs -n ai-pipeline deployment/pipeline-dashboard
```

**Common causes:**
- Missing dependencies
- Database/storage errors
- Missing environment variables

**Solutions:**
```bash
# Check logs for specific error
kubectl logs -n ai-pipeline deployment/pipeline-dashboard | tail -100

# Exec into pod to debug
kubectl exec -it deployment/pipeline-dashboard -n ai-pipeline -- bash

# Test manually
uv run python main.py dashboard --port 5000 --host 0.0.0.0
```

### Problem: Dashboard shows no data

**Diagnosis:**
```bash
# Check if data directories exist and have content
kubectl exec deployment/pipeline-dashboard -n ai-pipeline -- ls -la /app/issues
kubectl exec deployment/pipeline-dashboard -n ai-pipeline -- ls -la /app/logs
```

**Solutions:**
```bash
# Run a pipeline phase to generate data
kubectl exec -it deployment/pipeline-dashboard -n ai-pipeline -- bash
uv run python main.py bug-fetch --limit 5

# Or run as a Job
kubectl create -f /vagrant/deploy/k8s/30-pipeline-job-template.yaml
```

---

## General Debugging

### Comprehensive Health Check

```bash
#!/bin/bash
echo "=== Node Status ==="
kubectl get nodes

echo "=== All Pods ==="
kubectl get pods -A

echo "=== AI Pipeline Namespace ==="
kubectl get all -n ai-pipeline

echo "=== Certificates ==="
kubectl get certificate -n ai-pipeline

echo "=== Secrets ==="
kubectl get secrets -n ai-pipeline

echo "=== PVCs ==="
kubectl get pvc -n ai-pipeline

echo "=== Events (Recent) ==="
kubectl get events -n ai-pipeline --sort-by='.lastTimestamp' | tail -20
```

### Log Collection

```bash
# Collect all logs
mkdir -p /tmp/k3s-logs

# System logs
sudo journalctl -u k3s > /tmp/k3s-logs/k3s-service.log

# Pod logs
for pod in $(kubectl get pods -n ai-pipeline -o name); do
  kubectl logs -n ai-pipeline $pod --all-containers > /tmp/k3s-logs/${pod//\//-}.log 2>&1
done

# Descriptions
kubectl describe all -n ai-pipeline > /tmp/k3s-logs/describe-all.txt

# Package logs
tar czf /vagrant/k3s-logs-$(date +%Y%m%d-%H%M%S).tar.gz -C /tmp k3s-logs/
```

### Reset Everything

```bash
#!/bin/bash
# Nuclear option: reset entire deployment

# Delete namespace
kubectl delete namespace ai-pipeline

# Delete cluster issuers
kubectl delete clusterissuer --all

# Reinstall cert-manager
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.4/cert-manager.yaml
sleep 30
cd /vagrant/deploy/scripts
sudo bash 02-install-cert-manager.sh

# Recreate everything
sudo bash 03-setup-certificates.sh
sudo bash 04-extract-ca-cert.sh
sudo bash 06-create-secrets.sh
sudo bash 05-build-images.sh

# Redeploy
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml
kubectl apply -f /vagrant/deploy/k8s/10-github-emulator.yaml
kubectl apply -f /vagrant/deploy/k8s/20-pipeline-dashboard.yaml
```

### Common kubectl Commands

```bash
# Watch resources
kubectl get pods -n ai-pipeline -w
kubectl get svc -n ai-pipeline -w

# Logs with follow
kubectl logs -f -n ai-pipeline deployment/pipeline-dashboard

# Describe for details
kubectl describe pod <pod-name> -n ai-pipeline
kubectl describe svc <service-name> -n ai-pipeline

# Exec for debugging
kubectl exec -it <pod-name> -n ai-pipeline -- /bin/bash

# Port forward for testing
kubectl port-forward -n ai-pipeline svc/pipeline-dashboard 5000:5000

# Copy files
kubectl cp ai-pipeline/<pod-name>:/app/logs ./local-logs

# Get YAML
kubectl get deployment <name> -n ai-pipeline -o yaml
```

### Performance Debugging

```bash
# Check node resources
kubectl describe nodes

# Check pod resources
kubectl top pods -n ai-pipeline  # Requires metrics-server

# Check events for resource issues
kubectl get events -n ai-pipeline --field-selector type=Warning
```

---

## Getting Help

If you're still stuck:

1. **Collect diagnostic information:**
   ```bash
   cd /vagrant/deploy/scripts
   bash 99-verify-cluster.sh > /tmp/cluster-status.txt 2>&1
   ```

2. **Check logs:**
   ```bash
   kubectl logs -n ai-pipeline deployment/pipeline-dashboard > /tmp/dashboard.log
   kubectl logs -n ai-pipeline deployment/github-emulator > /tmp/emulator.log
   ```

3. **Review recent events:**
   ```bash
   kubectl get events -n ai-pipeline --sort-by='.lastTimestamp' | tail -50
   ```

4. **Check the project documentation:**
   - Main README: `/vagrant/CLAUDE.md`
   - Deployment README: `/vagrant/deploy/README.md`

5. **Create an issue** with:
   - What you were trying to do
   - Error messages
   - Output from verification script
   - Relevant logs
