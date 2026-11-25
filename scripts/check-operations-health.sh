#!/usr/bin/env bash
set +x
set -euo pipefail

fail() {
  printf '::error::%s\n' "$1" >&2
  exit 1
}

validate_only=false
case "$#:${1:-}" in
  0:) ;;
  1:--validate-url) validate_only=true ;;
  *) fail "Aufruf: $0 [--validate-url]" ;;
esac

# Only accept the LearningSteps origin on an AKS-managed default domain.
if [[ ! "${APP_URL:-}" =~ ^https://learningsteps\.[0-9a-f]{24}\.[a-z0-9]+\.aksapp\.io$ ]]; then
  fail "OPERATIONS_APP_URL muss die LearningSteps-HTTPS-Adresse auf einer AKS-Standarddomain ohne Pfad enthalten."
fi
if [[ "$validate_only" == true ]]; then
  exit 0
fi

body=$(mktemp)
trap 'rm -f -- "$body"' EXIT

request() {
  local path="$1" expected="$2" output="$3" metadata code status reason
  local -a limits=()
  if [[ "$output" != /dev/null ]]; then
    limits=(--max-filesize 65536)
  fi

  # Ignore curlrc, verify TLS and do not follow redirects. Log no response
  # bodies, raw headers or curl diagnostics.
  metadata=$(curl --disable --silent --proto '=https' \
    --connect-timeout 5 --max-time 10 "${limits[@]}" \
    --output "$output" --write-out '%{http_code}\n%{content_type}' \
    -- "$APP_URL$path" 2>/dev/null) || {
    code=$?
    case "$code" in
      5|6) reason="DNS-Fehler. OPERATIONS_APP_URL und DNS nach dem Rebuild prüfen." ;;
      35|51|58|59|60|77|83|90|91) reason="TLS-Fehler. Zertifikat und Hostnamen prüfen." ;;
      63) reason="Unerwartete Antwort. Maximale Größe überschritten." ;;
      7|28) reason="Verbindungsfehler oder Zeitüberschreitung." ;;
      *) reason="Transportfehler." ;;
    esac
    printf '%s (Pfad %s, curl %s)\n' "$reason" "$path" "$code" >&2
    return 1
  }

  status=${metadata%%$'\n'*}
  if [[ ! "$status" =~ ^[1-5][0-9]{2}$ ]]; then
    printf 'Unerwartete HTTP-Metadaten für %s.\n' "$path" >&2
    return 1
  fi
  if [[ "$status" != "$expected" ]]; then
    printf 'HTTP-Fehler für %s. Erhalten %s, erwartet %s.\n' "$path" "$status" "$expected" >&2
    return 1
  fi
  HTTP_CONTENT_TYPE=${metadata#*$'\n'}
}

readiness() {
  local path="/api/health/ready" media_type
  request "$path" 200 "$body" || return 1

  media_type=${HTTP_CONTENT_TYPE%%;*}
  if [[ ! "${media_type,,}" =~ ^[[:blank:]]*application/json[[:blank:]]*$ ]]; then
    printf 'Unerwarteter Content-Type für %s. Erwartet application/json.\n' "$path" >&2
    return 1
  fi
  if ! jq -es 'length == 1 and (.[0] |
    type == "object" and .status == "ready" and .database == "connected")' \
    "$body" >/dev/null 2>&1; then
    printf 'Unerwartete JSON-Antwort für %s. Erwartet status=ready und database=connected.\n' "$path" >&2
    return 1
  fi
}

ready=false
for attempt in {1..30}; do
  if readiness; then
    ready=true
    break
  fi
  printf 'API-Readiness nicht bestätigt (Versuch %s/30).\n' "$attempt" >&2
  if (( attempt < 30 )); then
    sleep 10
  fi
done
[[ "$ready" == true ]] || fail "API-Readiness nach 30 Versuchen nicht bestätigt."
echo "PASS: API-Readiness und Datenbankverbindung bestätigt."

request / 200 /dev/null || fail "Frontend-Check fehlgeschlagen."
request /api/entries 401 /dev/null || fail "Check des API-Zugriffs ohne Anmeldung fehlgeschlagen."
echo "PASS: Frontend HTTP 200 und API ohne Anmeldung HTTP 401."
