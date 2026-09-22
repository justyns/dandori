#!/bin/sh
# Exits 0 silently when DORI_DIR is unset or has no ledger.
set -u

[ -n "${DORI_DIR:-}" ] || exit 0
[ -d "$DORI_DIR/items" ] || exit 0

dori guide 2>/dev/null
echo
dori list --status inflight 2>/dev/null
exit 0
