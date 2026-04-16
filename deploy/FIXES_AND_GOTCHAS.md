# GitHub Emulator K3s Deployment - Fixes and Gotchas

This document summarizes the issues we encountered and fixed when deploying the github-emulator to k3s.

## Critical Fixes

### 1. DATABASE_URL Path Issue (CRITICAL)

**Problem**: The application was failing with `sqlite3.OperationalError: unable to open database file`

**Root Cause**: SQLite URL used 3 slashes instead of 4:
- `sqlite+aiosqlite:///data/github_emulator.db` ← 3 slashes = relative path from `/app/`
- Tried to create database at `/app/data/github_emulator.db` (doesn't exist)

**Fix**: Use 4 slashes for absolute path:
```
sqlite+aiosqlite:////data/github_emulator.db
```

**Where Fixed**: `deploy/repos/github-emulator/Dockerfile.k3s` line 28

**Why This Matters**: The working directory in the container is `/app`, so a relative path would resolve to the wrong location.

### 2. Environment Variable Collision

**Problem**: Application was crashing with:
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
PORT
  Input should be a valid integer, unable to parse string as an integer
  [type=int_parsing, input_value='tcp://10.43.221.250:443', input_type=str]
```

**Root Cause**: Kubernetes automatically creates environment variables for services:
- Service named `github-emulator` creates `GITHUB_EMULATOR_PORT=tcp://10.43.221.250:443`
- The app's config uses `env_prefix: "GITHUB_EMULATOR_"`, so it reads `GITHUB_EMULATOR_PORT`
- Pydantic tries to parse the service URL as an integer → fails

**Fix**: Explicitly set `GITHUB_EMULATOR_PORT=8000` in the deployment env vars to override the k8s-generated one.

**Where Fixed**: `deploy/k8s/10-github-emulator.yaml` lines 74-75

**Lesson Learned**: Be careful with Kubernetes service names - they generate environment variables that can collide with your app's config.

### 3. Container Port Mismatch

**Problem**: Service couldn't route traffic to Caddy

**Root Cause**: Container ports were set to `3000`, but Caddy listens on `443` and `80`

**Fix**: Updated container ports in deployment to match Caddy:
```yaml
ports:
- name: https
  containerPort: 443
- name: http
  containerPort: 80
```

**Where Fixed**: `deploy/k8s/10-github-emulator.yaml` lines 67-72

### 4. Service targetPort Mismatch

**Problem**: Service was routing to the wrong ports

**Root Cause**: Service had `targetPort: 3000` for both HTTPS and HTTP

**Fix**: Updated service targetPorts to match container ports:
```yaml
ports:
  - name: https
    port: 443
    targetPort: 443
  - name: http
    port: 80
    targetPort: 80
```

**Where Fixed**: `deploy/k8s/10-github-emulator.yaml` lines 15-22

## Build Script Issues

### 5. Main Pipeline Dockerfile PATH Issue

**Problem**: The auto-generated Dockerfile in `05-build-images.sh` had wrong uv installation path

**Root Cause**: Used `/root/.cargo/bin` instead of `/root/.local/bin`

**Fix**: Updated PATH in auto-generated Dockerfile and made pipeline build optional

**Where Fixed**: `deploy/scripts/05-build-images.sh` line 38

### 6. Wrong Source Directory

**Problem**: Build script looked for github-emulator at `/vagrant/.context/github-emulator`

**Root Cause**: Incorrect path in original script

**Fix**: Updated to `/vagrant/deploy/repos/github-emulator`

**Where Fixed**: `deploy/scripts/05-build-images.sh` line 62

## Improvements Made

### 7. Dedicated Build Script

**Created**: `deploy/scripts/05a-build-github-emulator.sh`

**Purpose**: Simplified script that only builds the github-emulator image, making it faster and clearer

**Benefits**:
- Doesn't try to build the main pipeline image (which may not be needed)
- Faster iteration during development
- Clearer error messages

### 8. ConfigMap for Caddyfile

**Created**: `deploy/k8s/09-github-emulator-config.yaml`

**Purpose**: Mount Caddyfile via ConfigMap instead of baking it into the image

**Benefits**:
- Can update Caddy config without rebuilding image
- Uses cert-manager certificates instead of Caddy's auto-generated ones
- Runtime configuration flexibility

## Testing & Verification

### What Works

✅ **Pod starts successfully**
```bash
kubectl get pods -n ai-pipeline
# github-emulator-xxx   1/1     Running
```

✅ **API responds on internal endpoint**
```bash
kubectl exec -n ai-pipeline deployment/github-emulator -- \
  curl -s http://127.0.0.1:8000/api/v3
```

✅ **HTTPS works via Caddy with cert-manager certificates**
```bash
kubectl run test-pod --rm -i --image=curlimages/curl --restart=Never -- \
  curl -k -s https://github-emulator.ai-pipeline.svc.cluster.local/api/v3
```

✅ **Database persists on PVC**
```bash
kubectl get pvc -n ai-pipeline github-emulator-data
# STATUS: Bound
```

### Known Limitations

⚠️ **LoadBalancer external access**: The LoadBalancer IP is on libvirt's internal network, not directly accessible from host. Use port-forward instead:
```bash
kubectl port-forward -n ai-pipeline svc/github-emulator 8443:443
```

⚠️ **Certificate doesn't include LoadBalancer IP**: The cert-manager certificate includes cluster DNS names but may not include all possible external IPs

## Quick Reference

### Rebuild and Redeploy

```bash
# Inside the Vagrant VM
cd /vagrant/deploy/scripts

# Rebuild image
sudo bash 05a-build-github-emulator.sh

# Restart deployment to pick up new image
kubectl rollout restart deployment/github-emulator -n ai-pipeline

# Check logs
kubectl logs -n ai-pipeline deployment/github-emulator --tail=50
```

### Common Debugging Commands

```bash
# Check pod status
kubectl get pods -n ai-pipeline -l app=github-emulator

# Check logs
kubectl logs -n ai-pipeline deployment/github-emulator

# Check environment variables
kubectl exec -n ai-pipeline deployment/github-emulator -- env | grep GITHUB_EMULATOR

# Test API directly (bypass Caddy)
kubectl exec -n ai-pipeline deployment/github-emulator -- \
  curl -s http://127.0.0.1:8000/api/v3

# Test via service DNS
kubectl run test-pod --rm -i --image=curlimages/curl --restart=Never -- \
  curl -k -s https://github-emulator.ai-pipeline.svc.cluster.local/api/v3

# Check certificate
kubectl get certificate -n ai-pipeline github-emulator-tls
kubectl describe certificate -n ai-pipeline github-emulator-tls

# Check ConfigMap
kubectl get configmap -n ai-pipeline github-emulator-config
kubectl describe configmap -n ai-pipeline github-emulator-config
```

## Architecture Decisions

### Why Dockerfile.k3s?

- Keeps original Dockerfile intact for docker-compose use
- Optimized for Kubernetes (no baked-in Caddyfile, runtime config via ConfigMap)
- Clear separation of concerns

### Why ConfigMap for Caddyfile?

- Runtime configuration without rebuilding image
- Easier to update TLS certificate paths
- Matches Kubernetes best practices

### Why PersistentVolume?

- Database persists across pod restarts
- Can be backed up separately
- Production-ready approach

### Why emptyDir Didn't Help?

Initially tried `emptyDir` to rule out PVC issues, but the problem was the DATABASE_URL path, not the volume type. Both PVC and emptyDir work fine once the path is fixed.

## Lessons Learned

1. **SQLite URL syntax matters**: 3 slashes vs 4 slashes makes a huge difference
2. **Watch for k8s env var collisions**: Service names generate environment variables
3. **Verify container ports**: Don't assume - check what the application actually listens on
4. **Read app config carefully**: Understanding `env_prefix` settings prevents env var issues
5. **Test incrementally**: We tested the API directly, then via Caddy, then via Service - this helped isolate issues
6. **Document fixes**: Future deployments will benefit from knowing these gotchas

## Related Files

- Main deployment guide: `deploy/GITHUB_DEPLOYMENT.md`
- Build script: `deploy/scripts/05a-build-github-emulator.sh`
- Deploy script: `deploy/scripts/07-deploy-github-emulator.sh`
- Dockerfile: `deploy/repos/github-emulator/Dockerfile.k3s`
- Deployment manifest: `deploy/k8s/10-github-emulator.yaml`
- ConfigMap: `deploy/k8s/09-github-emulator-config.yaml`
