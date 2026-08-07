#!/usr/bin/env bash
#
# Import the NOMAD reprocessing Kibana dashboard into a running Kibana instance.
#
# Creates (or overwrites) the `nomad-logs-*` index pattern, the supporting
# visualizations and saved search, and the "NOMAD Reprocessing Errors"
# dashboard, then sets the index pattern as the Discover default.
#
# By default the `nomad.entry_id` / `nomad.upload_id` columns link to a filtered
# Kibana Discover view. Set NOMAD_GUI_URL to point the entry column at a NOMAD
# v2 GUI instead, so clicking an entry id opens that entry in NOMAD. The GUI base
# URL cannot be derived from the logs, so it must be supplied here.
#
# Usage:
#   KIBANA_URL=http://localhost:5601 ./scripts/setup_kibana.sh [bundle.ndjson]
#
#   # link the entry column to the v2 GUI (dev server on :3001, app 'entries'):
#   NOMAD_GUI_URL=http://localhost:3001 ./scripts/setup_kibana.sh
#
#   # deployment (v2 GUI served under /nomad-oasis/gui/v2), custom app path:
#   NOMAD_GUI_URL=https://my.oasis/nomad-oasis/gui/v2 NOMAD_APP_PATH=entries \
#     ./scripts/setup_kibana.sh
#
#   # full control over the link templates ({{value}} = the field value):
#   ENTRY_URL_TEMPLATE='https://my.oasis/.../apps/entries/{{value}}' \
#   UPLOAD_URL_TEMPLATE='https://my.oasis/.../uploads/upload/id/{{value}}' \
#     ./scripts/setup_kibana.sh
#
set -euo pipefail

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
NOMAD_GUI_URL="${NOMAD_GUI_URL:-}"
NOMAD_APP_PATH="${NOMAD_APP_PATH:-entries}"
ENTRY_URL_TEMPLATE="${ENTRY_URL_TEMPLATE:-}"
UPLOAD_URL_TEMPLATE="${UPLOAD_URL_TEMPLATE:-}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="${1:-$HERE/../ops/kibana/nomad_dashboard.ndjson}"

if [[ ! -f "$BUNDLE" ]]; then
  echo "Dashboard bundle not found: $BUNDLE" >&2
  exit 1
fi

echo "Importing $(basename "$BUNDLE") into $KIBANA_URL ..."
curl -fsS -X POST "$KIBANA_URL/api/saved_objects/_import?overwrite=true" \
  -H "kbn-xsrf: true" --form file=@"$BUNDLE"
echo

echo "Setting nomad-logs-* as the default index pattern ..."
curl -fsS -X POST "$KIBANA_URL/api/kibana/settings/defaultIndex" \
  -H "kbn-xsrf: true" -H "Content-Type: application/json" \
  -d '{"value":"nomad-logs"}' >/dev/null

# Derive the entry link template from NOMAD_GUI_URL if not set explicitly.
if [[ -z "$ENTRY_URL_TEMPLATE" && -n "$NOMAD_GUI_URL" ]]; then
  ENTRY_URL_TEMPLATE="${NOMAD_GUI_URL%/}/apps/${NOMAD_APP_PATH}/{{value}}"
fi

# Re-point the id columns whenever a NOMAD template is in play. Fields without a
# NOMAD template fall back to the in-Kibana Discover link.
if [[ -n "$ENTRY_URL_TEMPLATE" || -n "$UPLOAD_URL_TEMPLATE" ]]; then
  echo "Pointing id columns at NOMAD ..."
  KIBANA_URL="$KIBANA_URL" \
  ENTRY_URL_TEMPLATE="$ENTRY_URL_TEMPLATE" \
  UPLOAD_URL_TEMPLATE="$UPLOAD_URL_TEMPLATE" \
  python3 - <<'PY'
import json, os, urllib.request

kb = os.environ["KIBANA_URL"]
entry_t = os.environ.get("ENTRY_URL_TEMPLATE") or ""
upload_t = os.environ.get("UPLOAD_URL_TEMPLATE") or ""


def kibana_discover(field):
    return (
        "/app/discover#/?_g=(time:(from:now-7d,to:now))"
        "&_a=(query:(language:kuery,query:'" + field + ":%22{{value}}%22'))"
    )


def fmt(tmpl):
    return {
        "id": "url",
        "params": {
            "urlTemplate": tmpl,
            "labelTemplate": "{{value}}",
            "openLinkInCurrentTab": False,
        },
    }


field_format_map = {
    "nomad.entry_id": fmt(entry_t or kibana_discover("nomad.entry_id")),
    "nomad.upload_id": fmt(upload_t or kibana_discover("nomad.upload_id")),
}
body = json.dumps(
    {"attributes": {"fieldFormatMap": json.dumps(field_format_map)}}
).encode()
req = urllib.request.Request(
    kb + "/api/saved_objects/index-pattern/nomad-logs",
    data=body,
    method="PUT",
    headers={"kbn-xsrf": "true", "Content-Type": "application/json"},
)
urllib.request.urlopen(req, timeout=20).read()
print("  entry_id  ->", entry_t or "(kibana discover)")
print("  upload_id ->", upload_t or "(kibana discover)")
PY
fi

echo "Done. Open: $KIBANA_URL/app/dashboards#/view/nomad-reprocessing-errors"
