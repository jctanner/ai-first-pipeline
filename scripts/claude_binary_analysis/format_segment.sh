#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 INPUT OUTPUT PRETTIER_BINARY" >&2
  exit 2
}

[[ $# -eq 3 ]] || usage
input=$1
output=$2
formatter=$3
expected_version=3.6.2

[[ -f "$input" && ! -L "$input" ]] || {
  echo "error: input must be a regular, non-symlink file" >&2
  exit 1
}
[[ -x "$formatter" ]] || {
  echo "error: explicit formatter is not executable: $formatter" >&2
  exit 1
}
actual_version=$("$formatter" --version)
[[ "$actual_version" == "$expected_version" ]] || {
  echo "error: expected Prettier $expected_version, got $actual_version" >&2
  exit 1
}

mkdir -p "$(dirname "$output")"
temporary=$(mktemp "$(dirname "$output")/.formatted.XXXXXX")
trap 'rm -f "$temporary"' EXIT
"$formatter" --ignore-path /dev/null --parser babel "$input" >"$temporary"
if [[ -e "$output" ]] && ! cmp -s "$temporary" "$output"; then
  echo "error: refusing to overwrite different formatted output: $output" >&2
  exit 1
fi
if [[ ! -e "$output" ]]; then
  mv "$temporary" "$output"
fi
trap - EXIT
rm -f "$temporary"
echo "$output"
