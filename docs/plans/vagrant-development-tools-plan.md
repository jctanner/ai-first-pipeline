# Vagrant Development Tools Installation

## Context

The `ai-pipeline` Vagrant VM needs a small set of interactive development and
cluster-debugging tools:

- Claude Code, installed with `https://claude.ai/install.sh`
- Codex, installed from the `@openai/codex` npm package
- Homebrew for Linux
- `stern`, installed with Homebrew

K3s already provides a compatible `kubectl`, so the development-tools script
will not install a second client through Homebrew.

These tools should be installed automatically near the end of initial Vagrant
provisioning, but the installation must not be embedded directly in the
`Vagrantfile`. The same installer must remain available for an existing VM so a
developer can install missing tools or repair an incomplete installation
without recreating the machine.

## Goals

1. Add one idempotent repository script that installs the four requested tools
   not already supplied by K3s.
2. Run user-scoped installers as the `vagrant` user, even when Vagrant invokes
   the provisioning script as root.
3. Make the installed commands available in both interactive and non-interactive
   `vagrant ssh -c` sessions.
4. Allow the script to be run manually after provisioning.
5. Fail clearly when an installation fails instead of leaving provisioning
   apparently successful.

## Proposed Script

Create `deploy/scripts/00-install-vagrant-tools.sh`.

The script will support these invocation forms:

```bash
# From the host
vagrant ssh -c 'sudo /vagrant/deploy/scripts/00-install-vagrant-tools.sh'

# From inside the VM
sudo /vagrant/deploy/scripts/00-install-vagrant-tools.sh
```

The default target user will be `vagrant`. An optional environment variable can
make the script usable in another Ubuntu VM:

```bash
TARGET_USER=ubuntu sudo -E /path/to/00-install-vagrant-tools.sh
```

The script should use `set -euo pipefail`, resolve the target user's home
directory through `getent passwd`, and reject execution when the user cannot be
resolved.

## Installation Order

The requested tools have an implicit dependency: installing Codex with npm
requires Node.js and npm, neither of which the current `Vagrantfile` installs.
Use the following order:

1. Install Homebrew prerequisites with apt.
2. Install Homebrew as the target user.
3. Install `node` and `stern` with Homebrew.
4. Install Codex with `npm install -g @openai/codex` as the target user.
5. Install Claude Code with `curl -fsSL https://claude.ai/install.sh | bash` as
   the target user.
6. Create `~/bin/claude.vertex` with the pipeline's Vertex AI project and
   region settings.
7. Verify every expected executable.

This preserves the requested installation mechanisms while ensuring npm exists
before it is used.

## User and Privilege Model

Vagrant shell provisioners run as root by default, but Homebrew and the agent
CLI installers should not populate `/root`.

Use a helper that invokes user-scoped commands with a login shell:

```bash
run_as_target() {
  sudo -H -u "$TARGET_USER" env HOME="$TARGET_HOME" bash -lc "$1"
}
```

Avoid running the Homebrew installer as root. System package installation and
creation of shared symlinks may run as root.

The implementation must quote commands carefully. For the two upstream curl
installers, download to a temporary file first and execute that file as the
target user. This avoids nested shell quoting in the Vagrant provisioner and
makes curl failures visible under `pipefail`.

## Homebrew Setup

Install the Linuxbrew prerequisites before invoking Homebrew:

```bash
apt-get update -qq
apt-get install -y -qq build-essential procps curl file git ca-certificates
```

On this Ubuntu image, Homebrew is expected at:

```text
/home/linuxbrew/.linuxbrew/bin/brew
```

Do not assume that location blindly. After installation, check the standard
Linuxbrew path and then fall back to resolving `brew` in the target user's login
shell. Fail if neither works.

Persist Homebrew's environment for the `vagrant` user in a dedicated file such
as `~/.config/ai-first-pipeline/tools-env.sh`:

```bash
eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
export PATH="$HOME/.local/bin:$HOME/bin:$PATH"
```

Source that file from both `~/.profile` and `~/.bashrc`, guarded by marker lines
or exact-match checks so repeated runs do not append duplicate entries.

Sourcing `~/.profile` matters for login sessions; sourcing the dedicated file
from `~/.bashrc` covers interactive Bash. For reliable non-interactive
`vagrant ssh -c` usage, also create symlinks for the final CLIs under
`/usr/local/bin` after verifying their resolved paths. The symlinks should be
updated atomically with `ln -sfn`.

## Idempotency

The installer should be safe to run repeatedly:

- Skip the Homebrew bootstrap when a working `brew` already exists.
- Use `brew install node stern`; Homebrew treats installed formulae as
  satisfied.
- Run `npm install -g @openai/codex` on every invocation so a manual rerun also
  refreshes Codex to the current package version.
- Skip the Claude installer when `claude` is already resolvable, unless
  `FORCE_UPDATE=1` is set.
- Rewrite the managed environment file rather than appending to it.
- Guard the single source line in `.profile` and `.bashrc` against duplicates.
- Refresh `/usr/local/bin` symlinks after installation.

No version pinning is proposed. Each fresh provision will receive the versions
currently published by the upstream installers and package managers.

## Vagrant Integration

Add a final shell provisioner to the `ai-pipeline` machine after the existing
system-preparation provisioner:

```ruby
pipeline.vm.provision "development-tools", type: "shell",
  path: "deploy/scripts/00-install-vagrant-tools.sh",
  args: ["vagrant"]
```

The script should accept the target username as its first positional argument,
with `TARGET_USER` and then `vagrant` as fallbacks. Using a named provisioner
allows it to be rerun independently:

```bash
vagrant provision --provision-with development-tools
```

Do not use `run: "always"`. These downloads should not execute on every
`vagrant up`; developers can explicitly rerun the named provisioner or invoke
the script inside the VM when they want updates.

## Verification

At the end of the script, run version checks as the target user and also through
the shared command paths:

```bash
claude --version
claude.vertex --version
codex --version
brew --version
kubectl version --client
stern --version
node --version
npm --version
```

After implementation, verify both installation paths.

Fresh or reprovisioned VM:

```bash
vagrant provision --provision-with development-tools
vagrant ssh -c 'claude --version'
vagrant ssh -c 'codex --version'
vagrant ssh -c 'stern --version'
vagrant ssh -c 'kubectl version --client'
```

Manual rerun and idempotency:

```bash
vagrant ssh -c 'sudo /vagrant/deploy/scripts/00-install-vagrant-tools.sh vagrant'
vagrant ssh -c 'sudo /vagrant/deploy/scripts/00-install-vagrant-tools.sh vagrant'
```

Both manual runs should succeed, and `.profile` and `.bashrc` should contain
only one managed source line each.

Finally, confirm that the K3s-provided `kubectl` client can reach the existing
cluster using the VM's configured kubeconfig:

```bash
vagrant ssh -c 'kubectl get nodes'
```

## Implementation Steps

1. Add `deploy/scripts/00-install-vagrant-tools.sh` with target-user handling,
   Homebrew bootstrap, formula installation, agent CLI installation, PATH
   management, and verification.
2. Add the named `development-tools` provisioner at the end of the VM's initial
   provisioning sequence in `Vagrantfile`.
3. Run a shell syntax check on the installer.
4. Run the named provisioner against the existing VM.
5. Rerun the installer manually to verify idempotency.
6. Verify command discovery through non-interactive `vagrant ssh -c` and confirm
   `kubectl get nodes` succeeds.

## Risks and Decisions

- **Unpinned upstream installers:** Reproducibility is lower, but this follows
  the requested update model. A future change can add optional version inputs.
- **Homebrew installation location:** The script will discover and verify the
  actual `brew` binary rather than relying only on the standard Linux path.
- **K3s kubectl:** K3s supplies the kubectl-compatible client used by this VM.
  The installer will not add a competing Homebrew client. Verification will
  confirm the K3s-provided command is available to the `vagrant` user and uses
  the existing kubeconfig.
- **Agent authentication:** Installing Claude and Codex does not configure
  credentials. Run `make vagrant-push-gcp-creds` to install the host's
  Application Default Credentials for the `vagrant` user and update the
  `gcp-credentials` Kubernetes secret.
- **Network dependency:** Initial provisioning requires access to GitHub,
  `claude.ai`, Homebrew repositories, and npm. Failures should stop only the
  named tool provisioner with a clear error, allowing it to be rerun later.
