#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 ANALYSIS_ROOT" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage
analysis_root=$(realpath "$1")
input_binary="$analysis_root/input/claude"
binary_manifest="$analysis_root/manifest/binary.json"
payload="$analysis_root/payload/bun-section.bin"

for tool in jq objcopy readelf sha256sum stat; do
  command -v "$tool" >/dev/null || {
    echo "error: required tool not found: $tool" >&2
    exit 1
  }
done
[[ -f "$input_binary" && -x "$input_binary" ]] || {
  echo "error: inspected input binary is missing: $input_binary" >&2
  exit 1
}
[[ -f "$binary_manifest" ]] || {
  echo "error: binary manifest is missing: $binary_manifest" >&2
  exit 1
}

input_sha=$(sha256sum "$input_binary" | awk '{print $1}')
recorded_sha=$(jq -er '.binary.sha256' "$binary_manifest")
[[ "$input_sha" == "$recorded_sha" ]] || {
  echo "error: input hash $input_sha differs from manifest $recorded_sha" >&2
  exit 1
}

section_line=$(readelf -SW "$input_binary" | awk '$2 == ".bun" {print; found=1} END {if (!found) exit 1}') || {
  echo "error: .bun ELF section not found" >&2
  exit 1
}
section_offset_hex=$(awk '{print $5}' <<<"$section_line")
section_size_hex=$(awk '{print $6}' <<<"$section_line")
section_offset=$((16#$section_offset_hex))
section_size=$((16#$section_size_hex))

tmp_payload=$(mktemp "$analysis_root/payload/.bun-section.bin.XXXXXX")
tmp_elf="$analysis_root/input/.objcopy-output.$$"
[[ ! -e "$tmp_elf" ]] || {
  echo "error: temporary objcopy output already exists: $tmp_elf" >&2
  exit 1
}
trap 'rm -f "$tmp_payload" "$tmp_elf"' EXIT
# objcopy rewrites INPUT in place when OUTPUT is omitted, even for a dump-only
# operation. Give it a disposable output so the immutable copied input remains
# byte-identical to the recorded source binary.
objcopy --dump-section ".bun=$tmp_payload" "$input_binary" "$tmp_elf"
actual_size=$(stat -c '%s' "$tmp_payload")
[[ "$actual_size" -eq "$section_size" ]] || {
  echo "error: extracted $actual_size bytes, ELF table records $section_size" >&2
  exit 1
}
payload_sha=$(sha256sum "$tmp_payload" | awk '{print $1}')

if [[ -e "$payload" ]]; then
  [[ -f "$payload" && ! -L "$payload" ]] || {
    echo "error: existing payload is not a regular, non-symlink file" >&2
    exit 1
  }
  existing_sha=$(sha256sum "$payload" | awk '{print $1}')
  [[ "$existing_sha" == "$payload_sha" ]] || {
    echo "error: refusing to overwrite payload $existing_sha with $payload_sha" >&2
    exit 1
  }
else
  mv "$tmp_payload" "$payload"
fi

tmp_manifest=$(mktemp "$analysis_root/manifest/.binary.json.XXXXXX")
jq \
  --argjson offset "$section_offset" \
  --arg offset_hex "0x$section_offset_hex" \
  --argjson size "$section_size" \
  --arg size_hex "0x$section_size_hex" \
  --arg sha256 "$payload_sha" \
  '.bun_section={offset:$offset,offset_hex:$offset_hex,size:$size,size_hex:$size_hex,sha256:$sha256}' \
  "$binary_manifest" >"$tmp_manifest"
if [[ $(jq -r '.bun_section // empty' "$binary_manifest") ]]; then
  cmp -s "$tmp_manifest" "$binary_manifest" || {
    rm -f "$tmp_manifest"
    echo "error: refusing to overwrite different recorded .bun metadata" >&2
    exit 1
  }
  rm -f "$tmp_manifest"
else
  mv "$tmp_manifest" "$binary_manifest"
fi
trap - EXIT
rm -f "$tmp_payload" "$tmp_elf"

echo "$payload"
