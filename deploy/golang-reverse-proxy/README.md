# Go Reverse Proxy for AI-First Pipeline

Simple, custom reverse proxy written in Go that provides clean HTTP/HTTPS access to the emulators and dashboard.

## Why Custom Proxy?

Traefik configuration proved overly complex for routing to Caddy HTTPS backends. This custom proxy:
- **Simple**: ~150 lines of Go code
- **Fast**: Minimal overhead, low resource usage
- **Flexible**: Easy to modify routes and behavior
- **Transparent**: Clear logging and debugging

## Architecture

```
External Request → Go Proxy (TLS termination) → Backend Services (HTTP)
                   ├─ github.local → github-emulator-backend:8000
                   ├─ jira.local → jira-emulator-backend:8080
                   └─ dashboard.local → pipeline-dashboard:5000
```

**TLS Strategy:**
- Proxy terminates TLS using cert-manager wildcard certificate
- Backends receive plain HTTP (no Caddy needed in ingress path)
- Internal pod-to-pod traffic still uses Caddy HTTPS (unchanged)

## Quick Start

Build and deploy:
```bash
./build-and-deploy.sh
```

This will:
1. Build Docker image inside Vagrant VM
2. Import to k3s
3. Deploy to `ai-pipeline` namespace
4. Wait for certificate and pod readiness
5. Show test commands

## Routes

| Host | Backend | Port |
|------|---------|------|
| `github-emulator.ai-pipeline.svc.cluster.local` | github-emulator-backend | 8000 |
| `github.local` | github-emulator-backend | 8000 |
| `jira-emulator.ai-pipeline.svc.cluster.local` | jira-emulator-backend | 8080 |
| `jira.local` | jira-emulator-backend | 8080 |
| `dashboard.ai-pipeline.svc.cluster.local` | pipeline-dashboard | 5000 |
| `dashboard.local` | pipeline-dashboard | 5000 |

## Testing

From your host machine (after port forwarding is set up):
```bash
# Test GitHub emulator
curl -k -H 'Host: github.local' https://localhost:8443/

# Test Jira emulator
curl -k -H 'Host: jira.local' https://localhost:9443/

# Test Dashboard
curl -k -H 'Host: dashboard.local' https://localhost:5443/
```

From inside the cluster:
```bash
kubectl run -n ai-pipeline test --rm -it --image=curlimages/curl --restart=Never -- \
  curl -H 'Host: jira.local' http://ingress-proxy/
```

## Configuration

Routes are defined in `main.go`:
```go
var routes = []Route{
    {
        Host:    "jira.local",
        Backend: "http://jira-emulator-backend.ai-pipeline.svc.cluster.local:8080",
    },
    // ...
}
```

To add new routes:
1. Edit `main.go`
2. Rebuild and redeploy: `./build-and-deploy.sh`

## Certificates

The proxy uses a cert-manager Certificate resource that covers:
- `*.ai-pipeline.svc.cluster.local` (wildcard)
- `*.local` (wildcard)
- Specific FQDNs for each service

The certificate is issued by the internal CA (`internal-ca-issuer`).

## Troubleshooting

View logs:
```bash
vagrant ssh -c 'kubectl logs -n ai-pipeline -l app=ingress-proxy -f'
```

Check service status:
```bash
vagrant ssh -c 'kubectl get svc -n ai-pipeline ingress-proxy'
```

Check certificate:
```bash
vagrant ssh -c 'kubectl get certificate -n ai-pipeline ingress-proxy-tls'
```

Describe pod for events:
```bash
vagrant ssh -c 'kubectl describe pod -n ai-pipeline -l app=ingress-proxy'
```

## Resource Usage

The proxy is lightweight:
- **Memory**: 64Mi request, 256Mi limit
- **CPU**: 50m request, 500m limit
- **Disk**: ~15MB image size

## Comparison to Traefik

| Feature | Custom Go Proxy | Traefik |
|---------|----------------|---------|
| Lines of config | ~150 | 1000+ |
| Memory usage | 64Mi | 512Mi+ |
| Easy to debug | ✅ Yes | ❌ No |
| Custom behavior | ✅ Trivial | ❌ Complex |
| Production ready | ⚠️ Basic | ✅ Full-featured |

For this lab environment, the custom proxy is perfect. For production with many services, advanced routing, and metrics, consider a full ingress controller.
