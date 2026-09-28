#!/usr/bin/env python3
"""Refuses to stop while this host holds a claim with nothing logged after it."""
import json
import os
import subprocess
import sys


def dori(*args):
    out = subprocess.run(["dori", *args, "--json"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["data"]


def main():
    data_dir = os.environ.get("DORI_DIR")
    if not data_dir or not os.path.isdir(os.path.join(data_dir, "items")):
        return
    if json.load(sys.stdin).get("stop_hook_active"):
        return
    host = dori("host")["host_id"]
    unlogged = []
    for it in dori("list", "--claimed"):
        if it.get("claim_expired"):
            continue
        events = dori("show", it["id"])["journal"]
        claims = [i for i, e in enumerate(events) if e["kind"] == "claim"]
        if not claims or events[claims[-1]]["host"] != host:
            continue
        if not any(e["kind"] == "log" for e in events[claims[-1] + 1:]):
            unlogged.append(f"{it['id']} ({it['claimed_by']})")
    if unlogged:
        print(f"dandori: claimed on this host with nothing logged since: {', '.join(unlogged)}. "
              'Run dori log "..." --ref <id> --actor <name>, or dori release <id> --actor <name>.',
              file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
