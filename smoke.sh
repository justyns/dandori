#!/usr/bin/env bash
# Runs the dori entry point end to end through uv. Behavior is covered by tests/.
set -euo pipefail

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cd "$(dirname "$0")"
export XDG_CONFIG_HOME="$WORK/xdg" DANDORI_HOST=smoketest DORI_DIR="$WORK/ledger"

uv run dori init
uv run dori upsert --ref forgejo:tsugite#868 --title "Mobile chat density" --source forgejo --actor alice
ID=$(ls "$DORI_DIR/items" | sed 's/\.md$//')
uv run dori claim "$ID" --actor alice
uv run dori log "starting work" --ref "$ID" --actor alice
uv run dori release "$ID" --actor alice
git init -q --bare "$WORK/origin.git"
git -C "$DORI_DIR" init -q
git -C "$DORI_DIR" remote add origin "$WORK/origin.git"
uv run dori sync
uv run dori status --json | python3 -c 'import json, sys; assert json.load(sys.stdin)["schema_version"] == 1'
echo "ALL SMOKE CHECKS PASSED"
