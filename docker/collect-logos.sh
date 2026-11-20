#!/bin/sh
# collect-logos - fills $LOGOS_DIR with project / group logos and writes manifest.json for login-skin.js
#
# Sources, in this order:
#   1. $LOGOS_CUSTOM_DIR      any images you mount yourself; a file named pinned.* is shown on every load
#   2. $LOGIN_SKIN_PINNED_URL an image URL used as the pinned logo
#   3. GitLab API             project and group avatars (and, optionally, logo files from repositories)
#   4. built-in demo logos    only when LOGO_DEMO=1
#
# Environment:
#   GITLAB_API_URL       default: $GITLAB_UPSTREAM/api/v4
#   GITLAB_TOKEN         token with read_api scope (or GITLAB_TOKEN_FILE=/path); without a token
#                        only what GitLab shows to anonymous users can be collected
#   LOGO_VISIBILITY      public (default) | internal (public + internal) | all | none (skip the API)
#   LOGO_GROUP           only this group and its subgroups, e.g. "infrastructure" or "a/b"
#   LOGO_REPO_FILES      space separated repo paths to try for projects WITHOUT an avatar,
#                        e.g. "logo.svg public/favicon.svg assets/branding/logo.svg"
#   LOGO_MAX             stop after this many logos (default 60)
#   LOGO_API_HOST        Host header for API calls when GITLAB_API_URL is an internal address
#   LOGO_API_INSECURE=1  do not verify TLS of GITLAB_API_URL
set -u

OUT="${LOGOS_DIR:-/var/lib/login-skin/logos}"
CUSTOM="${LOGOS_CUSTOM_DIR:-/logos-custom}"
DEMO_DIR="${LOGOS_DEMO_DIR:-/usr/share/nginx/html/login-skin/demo-logos}"
API="${GITLAB_API_URL:-${GITLAB_UPSTREAM:-}/api/v4}"
VIS="${LOGO_VISIBILITY:-public}"
MAX="${LOGO_MAX:-60}"
TOKEN="${GITLAB_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -n "${GITLAB_TOKEN_FILE:-}" ] && [ -r "$GITLAB_TOKEN_FILE" ]; then
  TOKEN="$(tr -d '\r\n' < "$GITLAB_TOKEN_FILE")"
fi

log() { echo "[login-skin] $*" >&2; }
TAB="$(printf '\t')"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$OUT" "$TMP/new"
count=0
tries=0
api_failed=0

# curl against the API; internal http upstreams get the headers GitLab expects behind a TLS proxy
req() {
  set -- -sS -m 40 "$@"
  [ -n "$TOKEN" ] && set -- -H "PRIVATE-TOKEN: $TOKEN" "$@"
  [ -n "${LOGO_API_HOST:-}" ] && set -- -H "Host: $LOGO_API_HOST" -H "X-Forwarded-Proto: https" -H "X-Forwarded-Ssl: on" "$@"
  [ "${LOGO_API_INSECURE:-0}" = "1" ] && set -- -k "$@"
  curl "$@"
}
api_json() { req -f "$API$1"; }

ext_of() {   # content-type -> extension
  case "$1" in
    image/png*) echo png ;; image/svg*) echo svg ;; image/jpeg*) echo jpg ;; image/webp*) echo webp ;;
    image/gif*) echo gif ;; image/x-icon*|image/vnd.microsoft.icon*) echo ico ;; *) echo "" ;;
  esac
}

sniff() {    # file -> extension by magic bytes (GitLab often answers application/octet-stream)
  h="$(head -c 16 "$1" | od -An -tx1 | tr -d ' 
')"
  case "$h" in
    89504e47*) echo png ;; ffd8ff*) echo jpg ;; 47494638*) echo gif ;; 00000100*) echo ico ;;
    52494646????????57454250*) echo webp ;;
    *) if head -c 1024 "$1" | grep -qi '<svg'; then echo svg; else echo ""; fi ;;
  esac
}

# save <api path> <basename> [forced extension]  -> 0 when an image was stored
save() {
  [ "$count" -ge "$MAX" ] && return 1
  tries=$((tries + 1))
  out="$(req -o "$TMP/dl" -w '%{http_code} %{content_type}' "$API$1" 2>/dev/null)" || return 1
  code="${out%% *}"; ctype="${out#* }"
  [ "$code" = "200" ] && [ -s "$TMP/dl" ] || return 1
  ext="${3:-$(ext_of "$ctype")}"
  [ -n "$ext" ] || ext="$(sniff "$TMP/dl")"
  [ -n "$ext" ] || return 1
  [ "$(wc -c < "$TMP/dl")" -le "${LOGO_MAX_BYTES:-1500000}" ] || return 1
  mv "$TMP/dl" "$TMP/new/$2.$ext"
  count=$((count + 1))
  return 0
}

urlenc() { jq -rn --arg v "$1" '$v|@uri'; }

# ---- 1. custom images ---------------------------------------------------------------------
if [ -d "$CUSTOM" ]; then
  for f in "$CUSTOM"/*; do
    [ -f "$f" ] || continue
    case "$(echo "$f" | tr 'A-Z' 'a-z')" in
      *.png|*.svg|*.jpg|*.jpeg|*.webp|*.gif|*.ico) cp "$f" "$TMP/new/$(basename "$f")" ;;
    esac
  done
fi

# ---- 2. pinned logo by URL -------------------------------------------------------------------
if [ -n "${LOGIN_SKIN_PINNED_URL:-}" ]; then
  out="$(curl -sSL -m 40 -o "$TMP/dl" -w '%{http_code} %{content_type}' "$LOGIN_SKIN_PINNED_URL" 2>/dev/null)" || out="000 "
  ext="$(ext_of "${out#* }")"
  if [ "${out%% *}" = "200" ] && [ -n "$ext" ]; then
    rm -f "$TMP"/new/pinned.*; mv "$TMP/dl" "$TMP/new/pinned.$ext"
  else
    log "pinned logo: could not download $LOGIN_SKIN_PINNED_URL ($out)"
  fi
fi

# ---- 3. GitLab API -----------------------------------------------------------------------------
case "$VIS" in
  public)   QVIS="&visibility=public"; SEL='.' ;;
  internal) QVIS="";                   SEL='select(.visibility != "private")' ;;
  all)      QVIS="";                   SEL='.' ;;
  *)        QVIS="";                   SEL='' ;;
esac

collect() {   # <list path with query> <kind: projects|groups> <file prefix>
  page=1
  while [ "$page" -le "${LOGO_PAGES:-30}" ] && [ "$count" -lt "$MAX" ] && [ "$tries" -lt $((MAX * 4 + 20)) ]; do
    json="$(api_json "$1&per_page=100&page=$page")" || { log "$2: API request failed (page $page)"; api_failed=1; return 1; }
    n="$(printf '%s' "$json" | jq 'if type == "array" then length else 0 end')" || return 1
    [ "$n" -gt 0 ] || break
    printf '%s' "$json" | jq -r ".[] | $SEL | [(.id|tostring), (.avatar_url // \"\")] | @tsv" > "$TMP/list"
    while IFS="$TAB" read -r id avatar; do
      [ "$count" -lt "$MAX" ] && [ "$tries" -lt $((MAX * 4 + 20)) ] || break
      if [ -n "$avatar" ]; then
        save "/$2/$id/avatar" "$3$id" || true
      elif [ "$2" = "projects" ] && [ -n "${LOGO_REPO_FILES:-}" ]; then
        for path in $LOGO_REPO_FILES; do
          e="$(echo "${path##*.}" | tr 'A-Z' 'a-z')"; [ "$e" = "jpeg" ] && e=jpg
          case "$e" in png|svg|jpg|webp|gif|ico) ;; *) continue ;; esac
          save "/projects/$id/repository/files/$(urlenc "$path")/raw?ref=HEAD" "$3$id" "$e" && break
        done
      fi
    done < "$TMP/list"
    [ "$n" -lt 100 ] && break
    page=$((page + 1))
  done
}

if [ -n "$SEL" ] && [ -n "$API" ] && [ "$API" != "/api/v4" ]; then
  if [ -n "${LOGO_GROUP:-}" ]; then
    g="$(urlenc "$LOGO_GROUP")"
    collect "/groups/$g/projects?include_subgroups=true&archived=false&order_by=last_activity_at$QVIS" projects p
    collect "/groups/$g/subgroups?all_available=true$QVIS" groups g
  else
    collect "/projects?archived=false&order_by=last_activity_at$QVIS" projects p
    collect "/groups?all_available=true$QVIS" groups g
  fi
fi

# ---- 4. demo logos -----------------------------------------------------------------------------
if [ "${LOGO_DEMO:-0}" = "1" ] && [ -d "$DEMO_DIR" ]; then
  cp "$DEMO_DIR"/* "$TMP/new/" 2>/dev/null || true
fi

# keep the previous set when the API was unreachable and gave us nothing new
if [ "$api_failed" = "1" ] && [ "$count" -eq 0 ] && [ -s "$OUT/manifest.json" ] \
   && [ "$(jq '.logos | length' "$OUT/manifest.json" 2>/dev/null || echo 0)" -gt 0 ]; then
  log "API unreachable - keeping the existing logos"
  exit 1
fi

# ---- de-duplicate identical images (same avatar on many projects) -------------------------------
( cd "$TMP/new" && for f in *; do [ -f "$f" ] && sha256sum "$f"; done ) 2>/dev/null | sort > "$TMP/sums"
awk 'seen[$1]++ { print $2 }' "$TMP/sums" | while read -r dup; do
  case "$dup" in pinned.*) ;; *) rm -f "$TMP/new/$dup" ;; esac
done

# ---- publish: files first, manifest last, then drop what is no longer listed ---------------------
( cd "$TMP/new" && ls -1 2>/dev/null ) > "$TMP/names"
jq -Rn '[inputs | select(length > 0)] as $all
        | { logos:  [$all[] | select(startswith("pinned.") | not)],
            pinned: ([$all[] | select(startswith("pinned."))] | first),
            generated: (now | floor) }' < "$TMP/names" > "$TMP/manifest.json" || exit 1
while read -r name; do [ -n "$name" ] && cp "$TMP/new/$name" "$OUT/$name"; done < "$TMP/names"
cp "$TMP/manifest.json" "$OUT/manifest.json.tmp" && mv "$OUT/manifest.json.tmp" "$OUT/manifest.json"
for f in "$OUT"/*; do
  [ -f "$f" ] || continue
  b="$(basename "$f")"
  [ "$b" = "manifest.json" ] && continue
  grep -qxF "$b" "$TMP/names" || rm -f "$f"
done
log "logos: $(jq '.logos | length' "$OUT/manifest.json"), pinned: $(jq -r '.pinned // "none"' "$OUT/manifest.json")"
