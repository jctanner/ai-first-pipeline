#!/bin/bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"
BACKUP_ROOT="${PROJECT_ROOT}/backups"

if [[ ! -d "${BACKUP_ROOT}" ]]; then
  echo "No backups directory found at ${BACKUP_ROOT}"
  exit 0
fi

backups=()
while IFS= read -r dir; do
  [[ -f "${dir}/manifest.json" ]] && backups+=("$dir")
done < <(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d | sort -r)

if [[ ${#backups[@]} -eq 0 ]]; then
  echo "No backups found in ${BACKUP_ROOT}"
  exit 0
fi

echo "=========================================="
echo "Available Backups"
echo "=========================================="
echo ""

printf "%-22s  %-8s  %s\n" "TIMESTAMP" "SIZE" "SERVICES"
printf "%-22s  %-8s  %s\n" "---------" "----" "--------"

for dir in "${backups[@]}"; do
  ts=$(jq -r .timestamp "${dir}/manifest.json" 2>/dev/null || basename "$dir")
  size=$(jq -r .total_size "${dir}/manifest.json" 2>/dev/null || du -sh "$dir" | cut -f1)
  services=$(jq -r '.backed_up | join(", ")' "${dir}/manifest.json" 2>/dev/null || echo "unknown")
  printf "%-22s  %-8s  %s\n" "$ts" "$size" "$services"
done

echo ""
echo "Total: ${#backups[@]} backup(s)"
echo ""
echo "To restore: restore.sh <backup-dir>"
