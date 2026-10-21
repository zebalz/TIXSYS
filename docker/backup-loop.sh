#!/bin/sh
# Automatic nightly backup. Runs inside the "backup" container.
# Each backup is one file in the backups/ folder: the database plus every uploaded file.
set -u

BACKUP_TIME_UTC="${BACKUP_TIME_UTC:-10:00}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"

make_backup() {
  stamp=$(date -u +%Y%m%d-%H%M%S)
  work=$(mktemp -d)
  if pg_dump --no-owner --no-privileges -f "$work/db.sql" && tar -C /data/media -cf "$work/media.tar" .; then
    echo "tixsys backup $stamp (automatic)" > "$work/manifest.txt"
    out="/backups/tixsys-auto-$stamp.tar.gz"
    if tar -C "$work" -czf "$out.part" db.sql media.tar manifest.txt; then
      mv "$out.part" "$out"
      chmod 600 "$out"
      echo "Backup saved: backups/$(basename "$out")"
    else
      rm -f "$out.part"
      echo "Backup FAILED while packing at $stamp" >&2
    fi
  else
    echo "Backup FAILED at $stamp" >&2
  fi
  rm -rf "$work"
  # Keep only the newest automatic backups.
  ls -1t /backups/tixsys-auto-*.tar.gz 2>/dev/null | tail -n "+$((BACKUP_KEEP + 1))" | while read -r old; do
    rm -f "$old"
  done
}

seconds_until_next() {
  now=$(date -u +%s)
  today=$(date -u +%Y-%m-%d)
  target=$(date -u -d "$today $BACKUP_TIME_UTC" +%s 2>/dev/null) || target=$((now + 86400))
  if [ "$target" -le "$now" ]; then
    target=$((target + 86400))
  fi
  echo $((target - now))
}

if [ "${1:-}" = "now" ]; then
  make_backup
  exit 0
fi

echo "Automatic backups: every day at $BACKUP_TIME_UTC UTC, keeping the newest $BACKUP_KEEP."
while true; do
  sleep "$(seconds_until_next)"
  make_backup
done
