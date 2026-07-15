#!/usr/bin/env bash
# Install interactive development tools for the Vagrant VM.

set -euo pipefail

TARGET_USER="${1:-${TARGET_USER:-vagrant}}"
FORCE_UPDATE="${FORCE_UPDATE:-0}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: Run this script as root (for example, with sudo)." >&2
  exit 1
fi

TARGET_PASSWD="$(getent passwd "${TARGET_USER}" || true)"
if [[ -z "${TARGET_PASSWD}" ]]; then
  echo "ERROR: Target user '${TARGET_USER}' does not exist." >&2
  exit 1
fi

IFS=: read -r _ _ TARGET_UID TARGET_GID _ TARGET_HOME _ <<<"${TARGET_PASSWD}"
TARGET_GROUP="$(getent group "${TARGET_GID}" | cut -d: -f1)"

if [[ -z "${TARGET_HOME}" || ! -d "${TARGET_HOME}" ]]; then
  echo "ERROR: Home directory for '${TARGET_USER}' is unavailable: ${TARGET_HOME}" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d /tmp/ai-first-pipeline-tools.XXXXXX)"
chmod 755 "${TMP_DIR}"
trap 'rm -rf "${TMP_DIR}"' EXIT

run_as_target() {
  sudo -H -u "${TARGET_USER}" \
    env HOME="${TARGET_HOME}" USER="${TARGET_USER}" LOGNAME="${TARGET_USER}" \
    bash -lc "$1"
}

echo "==> Installing system prerequisites for development tools..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq build-essential procps curl file git ca-certificates

BREW_BIN=""
if [[ -x /home/linuxbrew/.linuxbrew/bin/brew ]]; then
  BREW_BIN=/home/linuxbrew/.linuxbrew/bin/brew
elif BREW_CANDIDATE="$(run_as_target 'command -v brew 2>/dev/null' || true)" && \
     [[ -n "${BREW_CANDIDATE}" && -x "${BREW_CANDIDATE}" ]]; then
  BREW_BIN="${BREW_CANDIDATE}"
fi

if [[ -z "${BREW_BIN}" ]]; then
  echo "==> Installing Homebrew for ${TARGET_USER}..."
  curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh \
    -o "${TMP_DIR}/install-homebrew.sh"
  chmod 755 "${TMP_DIR}/install-homebrew.sh"
  chown "${TARGET_UID}:${TARGET_GID}" "${TMP_DIR}/install-homebrew.sh"
  sudo -H -u "${TARGET_USER}" \
    env HOME="${TARGET_HOME}" USER="${TARGET_USER}" LOGNAME="${TARGET_USER}" NONINTERACTIVE=1 \
    /bin/bash "${TMP_DIR}/install-homebrew.sh"

  if [[ -x /home/linuxbrew/.linuxbrew/bin/brew ]]; then
    BREW_BIN=/home/linuxbrew/.linuxbrew/bin/brew
  else
    BREW_BIN="$(run_as_target 'command -v brew 2>/dev/null' || true)"
  fi
fi

if [[ -z "${BREW_BIN}" || ! -x "${BREW_BIN}" ]]; then
  echo "ERROR: Homebrew installation completed without a usable brew executable." >&2
  exit 1
fi

echo "==> Configuring Homebrew environment for ${TARGET_USER}..."
TOOLS_CONFIG_DIR="${TARGET_HOME}/.config/ai-first-pipeline"
TOOLS_ENV="${TOOLS_CONFIG_DIR}/tools-env.sh"
install -d -m 755 -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${TOOLS_CONFIG_DIR}"

BREW_PREFIX="$(sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" "${BREW_BIN}" --prefix)"
{
  echo '# Managed by /vagrant/deploy/scripts/00-install-vagrant-tools.sh'
  # shellcheck disable=SC2016 # $() and $HOME must be evaluated when sourced.
  printf 'eval "$(%q shellenv)"\n' "${BREW_BIN}"
  # shellcheck disable=SC2016 # $HOME and $PATH must be evaluated when sourced.
  echo 'export PATH="$HOME/.local/bin:$HOME/bin:$PATH"'
} >"${TOOLS_ENV}"
chown "${TARGET_UID}:${TARGET_GID}" "${TOOLS_ENV}"
chmod 644 "${TOOLS_ENV}"

# shellcheck disable=SC2016 # $HOME must be evaluated by the target user's shell.
SOURCE_LINE='[[ -f "$HOME/.config/ai-first-pipeline/tools-env.sh" ]] && source "$HOME/.config/ai-first-pipeline/tools-env.sh"'
for startup_file in "${TARGET_HOME}/.profile" "${TARGET_HOME}/.bashrc"; do
  touch "${startup_file}"
  chown "${TARGET_UID}:${TARGET_GID}" "${startup_file}"
  if ! grep -Fqx "${SOURCE_LINE}" "${startup_file}"; then
    printf '\n%s\n' "${SOURCE_LINE}" >>"${startup_file}"
  fi
done

TARGET_PATH="${BREW_PREFIX}/bin:${BREW_PREFIX}/sbin:${TARGET_HOME}/.local/bin:${TARGET_HOME}/bin:/usr/local/bin:/usr/bin:/bin"

echo "==> Installing Node.js and stern with Homebrew..."
sudo -H -u "${TARGET_USER}" \
  env HOME="${TARGET_HOME}" USER="${TARGET_USER}" LOGNAME="${TARGET_USER}" PATH="${TARGET_PATH}" \
  "${BREW_BIN}" install node stern

echo "==> Installing Codex..."
sudo -H -u "${TARGET_USER}" \
  env HOME="${TARGET_HOME}" USER="${TARGET_USER}" LOGNAME="${TARGET_USER}" PATH="${TARGET_PATH}" \
  "${BREW_PREFIX}/bin/npm" install -g @openai/codex

CLAUDE_BIN="$(sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" bash -c 'command -v claude 2>/dev/null' || true)"
if [[ -z "${CLAUDE_BIN}" || "${FORCE_UPDATE}" == "1" ]]; then
  echo "==> Installing Claude Code..."
  curl -fsSL https://claude.ai/install.sh -o "${TMP_DIR}/install-claude.sh"
  chmod 755 "${TMP_DIR}/install-claude.sh"
  chown "${TARGET_UID}:${TARGET_GID}" "${TMP_DIR}/install-claude.sh"
  sudo -H -u "${TARGET_USER}" \
    env HOME="${TARGET_HOME}" USER="${TARGET_USER}" LOGNAME="${TARGET_USER}" PATH="${TARGET_PATH}" \
    /bin/bash "${TMP_DIR}/install-claude.sh"
else
  echo "==> Claude Code already installed; skipping (set FORCE_UPDATE=1 to refresh)."
fi

echo "==> Configuring Claude Code for Vertex AI..."
CLAUDE_VERTEX_BIN="${TARGET_HOME}/bin/claude.vertex"
install -d -m 755 -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${TARGET_HOME}/bin"
cat >"${CLAUDE_VERTEX_BIN}" <<'EOF'
#!/usr/bin/env bash

export CLAUDE_CODE_USE_VERTEX=1
export CLOUD_ML_REGION=global
export ANTHROPIC_VERTEX_PROJECT_ID=itpc-gcp-ai-eng-claude

exec "$HOME/.local/bin/claude" "$@"
EOF
chown "${TARGET_UID}:${TARGET_GID}" "${CLAUDE_VERTEX_BIN}"
chmod 755 "${CLAUDE_VERTEX_BIN}"

echo "==> Publishing development tools in /usr/local/bin..."
declare -A TOOL_PATHS=(
  [brew]="${BREW_BIN}"
  [node]="${BREW_PREFIX}/bin/node"
  [npm]="${BREW_PREFIX}/bin/npm"
  [codex]="${BREW_PREFIX}/bin/codex"
  [stern]="${BREW_PREFIX}/bin/stern"
)

CLAUDE_BIN="$(sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" bash -c 'command -v claude 2>/dev/null' || true)"
TOOL_PATHS[claude]="${CLAUDE_BIN}"

for tool in brew node npm codex stern claude; do
  tool_path="${TOOL_PATHS[${tool}]}"
  if [[ -z "${tool_path}" || ! -x "${tool_path}" ]]; then
    echo "ERROR: Expected executable '${tool}' was not installed." >&2
    exit 1
  fi
  ln -sfn "${tool_path}" "/usr/local/bin/${tool}"
done

echo "==> Verifying installed development tools..."
sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" claude --version
sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" codex --version
sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" brew --version
sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" stern --version
sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" node --version
sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" npm --version
sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" claude.vertex --version

if command -v kubectl >/dev/null 2>&1; then
  sudo -H -u "${TARGET_USER}" env HOME="${TARGET_HOME}" PATH="${TARGET_PATH}" kubectl version --client
else
  echo "==> K3s kubectl is not installed yet; it will be supplied by the K3s provisioner."
fi

echo "==> Vagrant development tools installation complete."
