# Setting Up GCP Credentials for Vertex AI

This guide explains how to set up Google Cloud Platform credentials for Claude agents running in the K3s cluster.

## Why Needed?

Claude agents use **Vertex AI** (Google Cloud's AI platform) to access Claude models. This requires:
- A GCP project with Vertex AI API enabled
- Authentication credentials

## Quick Setup

### Step 1: Authenticate with GCP (Host Machine)

```bash
# Install gcloud CLI if needed
# https://cloud.google.com/sdk/docs/install

# Login and create application default credentials
gcloud auth application-default login

# Set your project
gcloud config set project YOUR-PROJECT-ID
```

This creates: `~/.config/gcloud/application_default_credentials.json`

### Step 2: Copy Credentials to Project

Run the helper script **on your host machine** (not in Vagrant):

```bash
cd /path/to/ai-first-pipeline
./deploy/scripts/11-create-gcp-credentials-secret.sh
```

This will:
1. Check if you have GCP credentials
2. Copy them to `.gcloud/` directory (gitignored)
3. Tell you to run the script again inside Vagrant

### Step 3: Create Kubernetes Secret

Run the script **inside Vagrant VM**:

```bash
vagrant ssh -c 'cd /vagrant/deploy/scripts && sudo bash 11-create-gcp-credentials-secret.sh'
```

This will:
1. Read credentials from `.gcloud/application_default_credentials.json`
2. Create Kubernetes secret `gcp-credentials` in `ai-pipeline` namespace
3. Verify the secret is valid

### Step 4: Verify

```bash
vagrant ssh -c "kubectl get secret gcp-credentials -n ai-pipeline"
```

Should show:
```
NAME              TYPE     DATA   AGE
gcp-credentials   Opaque   1      1m
```

## Alternative: Manual Creation

If you prefer to do it manually:

```bash
# On host machine
gcloud auth application-default login

# Copy credentials to shared location
mkdir -p .gcloud
cp ~/.config/gcloud/application_default_credentials.json .gcloud/

# Inside Vagrant VM
vagrant ssh
kubectl create secret generic gcp-credentials \
  -n ai-pipeline \
  --from-file=credentials.json=/vagrant/.gcloud/application_default_credentials.json
```

## What Services Need This?

Any service that uses Claude via Vertex AI needs these credentials:

✅ **Pipeline Dashboard** (already configured)
```yaml
env:
- name: GOOGLE_APPLICATION_CREDENTIALS
  value: /secrets/gcp/credentials.json
volumeMounts:
- name: gcp-credentials
  mountPath: /secrets/gcp
  readOnly: true
volumes:
- name: gcp-credentials
  secret:
    secretName: gcp-credentials
    optional: true  # Won't fail if missing
```

✅ **Claude Agent** (new - in deploy/claude-agent/)
- Same pattern as above

## Credential Types

### User Credentials (Recommended for Development)

Created by: `gcloud auth application-default login`

```json
{
  "type": "authorized_user",
  "client_id": "...",
  "client_secret": "...",
  "refresh_token": "..."
}
```

**Pros:**
- Easy to set up
- Uses your personal GCP account
- Good for development

**Cons:**
- Tied to your personal account
- Requires periodic re-authentication

### Service Account Credentials (Recommended for Production)

Created by: `gcloud iam service-accounts keys create`

```json
{
  "type": "service_account",
  "project_id": "...",
  "private_key_id": "...",
  "private_key": "...",
  "client_email": "...",
  "client_id": "...",
  "auth_uri": "...",
  "token_uri": "...",
  "auth_provider_x509_cert_url": "...",
  "client_x509_cert_url": "..."
}
```

**Pros:**
- Not tied to a user
- No re-authentication needed
- Better for automation

**Cons:**
- More complex to set up
- Need to manage key rotation

## Troubleshooting

### "Permission denied" errors

```bash
# Check if credentials file exists and is readable
vagrant ssh -c "kubectl get secret gcp-credentials -n ai-pipeline -o jsonpath='{.data.credentials\.json}' | base64 -d | jq ."
```

### "Invalid credentials" errors

Your credentials may have expired. Re-authenticate:

```bash
gcloud auth application-default login
./deploy/scripts/11-create-gcp-credentials-secret.sh  # On host
vagrant ssh -c 'cd /vagrant/deploy/scripts && sudo bash 11-create-gcp-credentials-secret.sh'  # In VM
```

### Check which project is configured

```bash
gcloud config get-value project
```

### Verify Vertex AI API is enabled

```bash
gcloud services list --enabled | grep aiplatform
```

If not enabled:

```bash
gcloud services enable aiplatform.googleapis.com
```

## Security Notes

### ✅ What We Do

- **`.gcloud/` is gitignored** - Credentials never committed
- **Read-only mounts** - Pods can't modify credentials
- **Secret-based** - Using Kubernetes Secrets, not ConfigMaps
- **Optional mounts** - Services don't fail if secret is missing

### ⚠️ Important

- **Credentials grant full Vertex AI access** - Anyone with access can make API calls
- **Costs apply** - Vertex AI API calls incur charges
- **Audit enabled** - All API calls logged in GCP Cloud Logging

### 🔐 Production Recommendations

For production, use **Workload Identity** instead of service account keys:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: claude-agent
  namespace: ai-pipeline
  annotations:
    iam.gke.io/gcp-service-account: claude-agent@PROJECT_ID.iam.gserviceaccount.com
```

Then bind the K8s service account to a GCP service account. No credentials file needed!

## Environment Variables

Services using Vertex AI need these env vars (already configured in deployments):

```bash
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-east5
ANTHROPIC_VERTEX_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp/credentials.json
```

These come from two sources:
1. **`pipeline-secrets`** Secret - First three variables
2. **`gcp-credentials`** Secret - credentials.json file

## Next Steps

After creating the secret:

1. **Deploy Claude Agent**:
   ```bash
   cd deploy/claude-agent
   ./build-and-deploy.sh
   ```

2. **Test Vertex AI access**:
   ```bash
   POD=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=claude-agent -o jsonpath='{.items[0].metadata.name}'")
   vagrant ssh -c "kubectl exec -n ai-pipeline $POD -- claude -p 'Say hello'"
   ```

3. **Monitor usage**: Check GCP Console → Vertex AI → Usage

## Files

| File | Purpose |
|------|---------|
| `~/.config/gcloud/application_default_credentials.json` | Created by gcloud CLI (host) |
| `.gcloud/application_default_credentials.json` | Copied to project (gitignored) |
| `deploy/scripts/11-create-gcp-credentials-secret.sh` | Helper script |
| Secret: `gcp-credentials` | Kubernetes secret in cluster |

## References

- [GCP Authentication Guide](https://cloud.google.com/docs/authentication/provide-credentials-adc)
- [Vertex AI Quickstart](https://cloud.google.com/vertex-ai/docs/start/cloud-environment)
- [Claude on Vertex AI](https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/use-claude)
