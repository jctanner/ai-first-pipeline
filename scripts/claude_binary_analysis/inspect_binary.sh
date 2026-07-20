#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 BINARY ANALYSIS_ROOT [SOURCE_TREE]" >&2
  exit 2
}

[[ $# -ge 2 && $# -le 3 ]] || usage

binary_source=$1
analysis_root=$2
source_tree=${3:-}

[[ -f "$binary_source" && ! -L "$binary_source" ]] || {
  echo "error: binary must be a regular, non-symlink file: $binary_source" >&2
  exit 1
}
[[ -x "$binary_source" ]] || {
  echo "error: binary is not executable: $binary_source" >&2
  exit 1
}

binary_source=$(realpath "$binary_source")
analysis_root=$(realpath -m "$analysis_root")
case "$analysis_root" in
  /|"$HOME"|"$HOME"/)
    echo "error: refusing broad analysis root: $analysis_root" >&2
    exit 1
    ;;
esac

for tool in file git jq ldd objcopy readelf sha256sum stat strings; do
  command -v "$tool" >/dev/null || {
    echo "error: required tool not found: $tool" >&2
    exit 1
  }
done

source_sha=$(sha256sum "$binary_source" | awk '{print $1}')
manifest_dir="$analysis_root/manifest"
input_dir="$analysis_root/input"
binary_manifest="$manifest_dir/binary.json"
input_binary="$input_dir/claude"

if [[ -f "$binary_manifest" ]]; then
  recorded_sha=$(jq -er '.binary.sha256' "$binary_manifest")
  [[ "$recorded_sha" == "$source_sha" ]] || {
    echo "error: immutable analysis root records $recorded_sha, not $source_sha" >&2
    exit 1
  }
fi

mkdir -p "$input_dir" "$manifest_dir" "$analysis_root/payload" \
  "$analysis_root/anchors" "$analysis_root/segments/raw" \
  "$analysis_root/segments/formatted" "$analysis_root/segments/pseudocode" \
  "$analysis_root/traces" "$analysis_root/fixtures" "$analysis_root/reports"

if [[ -e "$input_binary" ]]; then
  [[ -f "$input_binary" && ! -L "$input_binary" ]] || {
    echo "error: existing input is not a regular, non-symlink file" >&2
    exit 1
  }
  input_sha=$(sha256sum "$input_binary" | awk '{print $1}')
  [[ "$input_sha" == "$source_sha" ]] || {
    echo "error: existing input hash $input_sha differs from source $source_sha" >&2
    exit 1
  }
else
  cp --preserve=mode,timestamps "$binary_source" "$input_binary"
fi

file "$input_binary" >"$manifest_dir/file.txt"
readelf -h "$input_binary" >"$manifest_dir/elf-header.txt"
readelf -SW "$input_binary" >"$manifest_dir/sections.txt"
readelf -lW "$input_binary" >"$manifest_dir/segments.txt"
ldd "$input_binary" >"$manifest_dir/dynamic-dependencies.txt" 2>&1 || true

build_id=$(readelf -n "$input_binary" | awk '/^[[:space:]]*Build ID:/ && !found {sub(/^[[:space:]]*Build ID: /, ""); print; found=1}')
[[ -n "$build_id" ]] || {
  echo "error: ELF Build ID not found" >&2
  exit 1
}

version_output=$(
  timeout 30 "$input_binary" --version 2>&1
) || {
  echo "error: binary --version failed" >&2
  exit 1
}

runtime_strings=$(strings -a -n 8 "$input_binary" | \
  awk '
    /Bun\/[0-9]|Bun v?[0-9]|Bun [0-9]/ { if (bun_n < 10) print; bun_n++; next }
    /JavaScriptCore|WebKit JSC/ { if (jsc_n < 30) print; jsc_n++ }
  ')

stat_size=$(stat -c '%s' "$binary_source")
stat_mode=$(stat -c '%a' "$binary_source")
stat_owner=$(stat -c '%U' "$binary_source")
stat_group=$(stat -c '%G' "$binary_source")
stat_mtime=$(stat -c '%y' "$binary_source")
if [[ -f "$binary_manifest" ]]; then
  recorded_at=$(jq -er '.recorded_at' "$binary_manifest")
else
  recorded_at=$(date --utc +%Y-%m-%dT%H:%M:%SZ)
fi

tool_versions=$(jq -n \
  --arg file "$(file --version | head -1)" \
  --arg readelf "$(readelf --version | head -1)" \
  --arg objcopy "$(objcopy --version | head -1)" \
  --arg strings "$(strings --version | head -1)" \
  --arg jq "$(jq --version)" \
  --arg git "$(git --version)" \
  '{file:$file,readelf:$readelf,objcopy:$objcopy,strings:$strings,jq:$jq,git:$git}')

existing_bun='null'
if [[ -f "$binary_manifest" ]]; then
  existing_bun=$(jq '.bun_section // null' "$binary_manifest")
fi

tmp_manifest=$(mktemp "$manifest_dir/.binary.json.XXXXXX")
jq -n \
  --arg recorded_at "$recorded_at" \
  --arg source_path "$binary_source" \
  --argjson size "$stat_size" \
  --arg mode "$stat_mode" \
  --arg owner "$stat_owner" \
  --arg group "$stat_group" \
  --arg mtime "$stat_mtime" \
  --arg sha256 "$source_sha" \
  --arg build_id "$build_id" \
  --arg version_output "$version_output" \
  --arg runtime_strings "$runtime_strings" \
  --argjson tool_versions "$tool_versions" \
  --argjson bun_section "$existing_bun" \
  '{schema_version:1,recorded_at:$recorded_at,binary:{source_path:$source_path,size:$size,mode:$mode,owner:$owner,group:$group,mtime:$mtime,sha256:$sha256,build_id:$build_id,version_output:$version_output},runtime_identifiers:($runtime_strings|split("\n")|map(select(length>0))),tools:$tool_versions,bun_section:$bun_section}' \
  >"$tmp_manifest"
if [[ -f "$binary_manifest" ]]; then
  cmp -s "$tmp_manifest" "$binary_manifest" || {
    rm -f "$tmp_manifest"
    echo "error: refusing to overwrite different binary manifest for the same version workspace" >&2
    exit 1
  }
  rm -f "$tmp_manifest"
else
  mv "$tmp_manifest" "$binary_manifest"
fi

if [[ -n "$source_tree" ]]; then
  source_tree=$(realpath "$source_tree")
  [[ -d "$source_tree/.git" || -f "$source_tree/.git" ]] || {
    echo "error: source baseline is not a Git worktree: $source_tree" >&2
    exit 1
  }
  source_head=$(git -C "$source_tree" rev-parse HEAD)
  source_dirty=$(git -C "$source_tree" status --porcelain=v1 --untracked-files=all)
  source_commit_time=$(git -C "$source_tree" show -s --format=%cI HEAD)
  source_subject=$(git -C "$source_tree" show -s --format=%s HEAD)
  tmp_source_manifest=$(mktemp "$manifest_dir/.source-baseline.json.XXXXXX")
  jq -n \
    --arg path "$source_tree" \
    --arg head "$source_head" \
    --arg commit_time "$source_commit_time" \
    --arg subject "$source_subject" \
    --arg dirty "$source_dirty" \
    '{schema_version:1,path:$path,head:$head,commit_time:$commit_time,subject:$subject,dirty:($dirty|split("\n")|map(select(length>0)))}' \
    >"$tmp_source_manifest"
  source_manifest="$manifest_dir/source-baseline.json"
  if [[ -f "$source_manifest" ]]; then
    cmp -s "$tmp_source_manifest" "$source_manifest" || {
      rm -f "$tmp_source_manifest"
      echo "error: refusing to overwrite different source baseline" >&2
      exit 1
    }
    rm -f "$tmp_source_manifest"
  else
    mv "$tmp_source_manifest" "$source_manifest"
  fi
fi

echo "$binary_manifest"
