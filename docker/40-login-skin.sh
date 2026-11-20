#!/bin/sh
# Starts the logo collector next to nginx: once now, then every LOGO_REFRESH_SECONDS.
set -u
dir="${LOGOS_DIR:-/var/lib/login-skin/logos}"
mkdir -p "$dir" 2>/dev/null || true
[ -f "$dir/manifest.json" ] || echo '{"logos":[],"pinned":null}' > "$dir/manifest.json"
(
  collect-logos || true
  every="${LOGO_REFRESH_SECONDS:-21600}"
  if [ "$every" -gt 0 ] 2>/dev/null; then
    while sleep "$every"; do collect-logos || true; done
  fi
) &
