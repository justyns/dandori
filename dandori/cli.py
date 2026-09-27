from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from dandori.core import (
    PREFIX_KINDS,
    STATUSES,
    DandoriError,
    Ledger,
    derive_project_from_cwd,
    host_config_path,
    humanize_age,
    machine_host_id,
    require_ledger,
    save_machine_host_id,
)

SCHEMA_VERSION = 1
PROJECT_FILTER_HELP = "filter to this project, or . for the cwd's git repo"


def _project_filter(project: Optional[str]) -> Optional[str]:
    if project != ".":
        return project
    derived = derive_project_from_cwd()
    if not derived:
        raise DandoriError(f"--project . needs a git repo, and {os.getcwd()} is not in one")
    return derived


def _csv(value):
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _add_sync_flags(p, eager: bool = False) -> None:
    if not eager:
        p.add_argument("--sync", action="store_true", help="run `dori sync` after this write")
        return
    group = p.add_mutually_exclusive_group()
    group.add_argument("--sync", action="store_true",
                       help="pull and push on this call even if sync.eager_claims is off")
    group.add_argument("--no-sync", action="store_true",
                       help="skip the pull and push on this call (local-only)")


def _sync_flag(args) -> Optional[bool]:
    if args.sync:
        return True
    if args.no_sync:
        return False
    return None


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dir", default=os.environ.get("DORI_DIR", "."),
        help="ledger data dir (default: $DORI_DIR or cwd)",
    )
    common.add_argument("--json", action="store_true", help="emit {schema_version, data} JSON")

    parser = argparse.ArgumentParser(
        prog="dori",
        epilog="run `dori guide` for how to use this ledger",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the data dir structure", parents=[common])

    p = sub.add_parser("host", help="show or set this machine's host identity (applies to every ledger)",
                       parents=[common])
    host_sub = p.add_subparsers(dest="host_action")
    p_host_set = host_sub.add_parser("set", help="set this machine's host id", parents=[common])
    p_host_set.add_argument("host_id")

    p = sub.add_parser("upsert", help="create or update an item, keyed by ref", parents=[common])
    p.add_argument("--ref", action="append", help="repeatable")
    p.add_argument("--title")
    p.add_argument("--project", help="freeform project name (default: derived from cwd's git remote on create)")
    p.add_argument("--no-project", action="store_true", help="suppress project auto-derivation on create")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--type")
    p.add_argument("--priority", type=int)
    p.add_argument("--due", help="YYYY-MM-DD, or '' to clear")
    p.add_argument("--tags", help="comma-separated, replaces the list")
    p.add_argument("--deps", help="comma-separated, replaces the list")
    p.add_argument("--links", help="comma-separated, merged into the existing list")
    p.add_argument("--description")
    p.add_argument("--source", required=True)
    p.add_argument("--actor")
    p.add_argument("--force", action="store_true",
                    help="overwrite title/description even if --source doesn't own them")
    p.add_argument("--stdin-json", action="store_true", help="read a list of item dicts from stdin")
    _add_sync_flags(p)

    p = sub.add_parser("log", help="append a journal line", parents=[common])
    p.add_argument("msg")
    p.add_argument("--ref")
    p.add_argument("--actor")
    _add_sync_flags(p)

    p = sub.add_parser("update", help="change fields on an existing item", parents=[common])
    p.add_argument("id_or_ref")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--title")
    p.add_argument("--type")
    p.add_argument("--priority", type=int)
    p.add_argument("--due", help="YYYY-MM-DD, or '' to clear")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--project", help="freeform project name")
    g.add_argument("--no-project", action="store_true", help="clear the project")
    p.add_argument("--tags", help="comma-separated, replaces the list")
    p.add_argument("--deps", help="comma-separated, replaces the list")
    p.add_argument("--actor")
    p.add_argument("--log", help="journal this message alongside the field change")
    _add_sync_flags(p)

    p = sub.add_parser("claim", help="claim an item (requires --actor)", parents=[common])
    p.add_argument("id_or_ref")
    p.add_argument("--actor")
    p.add_argument("--log", help="journal this message alongside the claim")
    _add_sync_flags(p, eager=True)

    p = sub.add_parser("release", help="release a claim (requires --actor)", parents=[common])
    p.add_argument("id_or_ref")
    p.add_argument("--actor")
    p.add_argument("--log", help="journal this message alongside the release")
    _add_sync_flags(p, eager=True)

    p = sub.add_parser("list", help="list items", parents=[common])
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("-p", "--project", help=PROJECT_FILTER_HELP)

    p = sub.add_parser("show", help="show an item plus its journal lines", parents=[common])
    p.add_argument("id_or_ref")

    p = sub.add_parser("status", help="overdue / in flight / ready / waiting overview",
                       parents=[common])
    p.add_argument("-p", "--project", help=PROJECT_FILTER_HELP)

    p = sub.add_parser("split", help="split a parent into child items (part-of + needs: deps)", parents=[common])
    p.add_argument("parent_id_or_ref")
    p.add_argument("titles", nargs="+", help="one or more child titles")
    p.add_argument("--source")
    p.add_argument("--actor")

    sub.add_parser("guide", help="how to use this ledger, from its current state", parents=[common])

    sub.add_parser(
        "doctor",
        help="scan for ledger problems; exits 1 only on error-severity findings, 0 for informational ones",
        parents=[common],
    )

    p = sub.add_parser("prefix", help="manage the ref/link prefix registry")
    prefix_sub = p.add_subparsers(dest="prefix_action", required=True)
    p_prefix_add = prefix_sub.add_parser("add", help="register a prefix", parents=[common])
    p_prefix_add.add_argument("name")
    p_prefix_add.add_argument("--kind", choices=PREFIX_KINDS, required=True)
    p_prefix_add.add_argument("--desc")
    prefix_sub.add_parser("list", help="list registered prefixes", parents=[common])

    sub.add_parser("sync", help="git add/commit (+ pull --rebase/push if origin exists)", parents=[common])

    return parser


def _print(args, data, human_lines: list[str]) -> None:
    for d in data if isinstance(data, list) else [data]:
        for key, label in (("ref_warning", "warning"), ("sync_warning", "warning"), ("source_note", "note")):
            if isinstance(d, dict) and d.get(key):
                print(f"{label}: {d[key]}", file=sys.stderr)
    if args.json:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "data": data}, indent=2, default=str))
    else:
        print("\n".join(human_lines))


def _item_line(it: dict) -> str:
    project = f"  [{it['project']}]" if it.get("project") else ""
    due = f"  due {it['due']}" if it.get("due") else ""
    progress = ""
    if it.get("children"):
        progress = f"  [{it.get('children_done', 0)}/{len(it['children'])} done]"
    tag = " [blocked]" if it.get("blocked") else ""
    claim = ""
    if it.get("claimed_by"):
        claim = f"  claimed {it['claimed_by']}, {humanize_age(it['claimed_at'])}"
    return f"{it['id']}  {it['title']} ({it.get('type')}, p{it.get('priority')}){project}{due}{progress}{tag}{claim}"


def _tree_lines(items: list[dict]) -> list[str]:
    """Nests each item under its part-of parent when the parent is also in the list."""
    by_id = {it["id"]: it for it in items}
    nested = {c for it in items for c in it.get("children", []) if c in by_id}
    lines: list[str] = []

    def walk(it: dict, depth: int) -> None:
        lines.append("  " * depth + _item_line(it))
        for c in it.get("children", []):
            if c in by_id:
                walk(by_id[c], depth + 1)

    for it in items:
        if it["id"] not in nested:
            walk(it, 0)
    return lines


def cmd_init(args) -> int:
    ledger = Ledger.init(args.dir)
    data = {"host_id": ledger.host_id, "path": str(ledger.data_dir)}
    _print(args, data, [f"initialized {ledger.data_dir} (host_id={ledger.host_id})"])
    return 0


def cmd_host(args) -> int:
    if args.host_action == "set":
        save_machine_host_id(args.host_id)
        data = {"host_id": args.host_id, "path": str(host_config_path())}
        _print(args, data, [f"host id set to {args.host_id} ({data['path']})"])
        return 0
    host_id = machine_host_id()
    _print(args, {"host_id": host_id, "path": str(host_config_path())}, [host_id])
    return 0


def cmd_upsert(ledger, args) -> int:
    if args.stdin_json:
        payload = json.loads(sys.stdin.read())
    else:
        if not args.ref and not args.title:
            raise DandoriError("upsert needs --ref or --title (or --stdin-json)")
        payload = {
            "refs": args.ref,
            "title": args.title,
            "project": args.project,
            "no_project": args.no_project,
            "status": args.status,
            "type": args.type,
            "priority": args.priority,
            "due": args.due,
            "tags": _csv(args.tags),
            "deps": _csv(args.deps),
            "links": _csv(args.links),
            "description": args.description,
        }
    result = ledger.upsert(payload, source=args.source, actor=args.actor,
                            sync=args.sync, force=args.force)
    items = result if isinstance(result, list) else [result]
    _print(args, result, [_item_line(it) for it in items])
    return 0


def cmd_log(ledger, args) -> int:
    entry = ledger.log(args.msg, ref=args.ref, actor=args.actor, sync=args.sync)
    _print(args, entry, [f"logged: {entry['msg']}"])
    return 0


def cmd_update(ledger, args) -> int:
    item = ledger.update(
        args.id_or_ref, actor=args.actor,
        status=args.status, title=args.title, type=args.type,
        priority=args.priority, due=args.due, project="" if args.no_project else args.project,
        tags=_csv(args.tags), deps=_csv(args.deps),
        log=args.log, sync=args.sync,
    )
    lines = [_item_line(item)]
    if args.log:
        lines.append(f"logged: {args.log}")
    _print(args, item, lines)
    return 0


def cmd_claim(ledger, args) -> int:
    item = ledger.claim(args.id_or_ref, args.actor, log=args.log, sync=_sync_flag(args))
    lines = [f"claimed {item['id']} for {args.actor}"]
    if args.log:
        lines.append(f"logged: {args.log}")
    _print(args, item, lines)
    return 0


def cmd_release(ledger, args) -> int:
    item = ledger.release(args.id_or_ref, args.actor, log=args.log, sync=_sync_flag(args))
    lines = [f"released {item['id']}"]
    if args.log:
        lines.append(f"logged: {args.log}")
    _print(args, item, lines)
    return 0


def cmd_list(ledger, args) -> int:
    items = ledger.items(status=args.status, project=_project_filter(args.project))
    _print(args, items, _tree_lines(items) or ["(no items)"])
    return 0


def cmd_show(ledger, args) -> int:
    result = ledger.show(args.id_or_ref)
    item, body, journal = result["item"], result["body"], result["journal"]
    lines = [_item_line(item)]
    if item.get("links"):
        lines.append(f"links: {', '.join(item['links'])}")
    if item.get("tags"):
        lines.append(f"tags: {', '.join(item['tags'])}")
    lines += ["", body.rstrip()]
    children = result.get("children")
    if children:
        lines.append("")
        lines.append("children:")
        lines += [f"  {_item_line(c)}  ({c['status']})" for c in children]
    lines.append("")
    lines.append("journal:")
    for e in journal:
        ref = f" ({e['ref']})" if e.get("ref") and e["ref"] != item["id"] else ""
        lines.append(f"  {e['ts']} {e['actor'] or '-'} [{e['kind']}] {e['msg']}{ref}")
    _print(args, result, lines)
    return 0


def cmd_split(ledger, args) -> int:
    result = ledger.split(args.parent_id_or_ref, args.titles, actor=args.actor, source=args.source)
    lines = [f"split {result['parent']['id']} into {len(result['children'])} children:"]
    lines += [f"  {c['id']}  {c['title']}" for c in result["children"]]
    _print(args, result, lines)
    return 0


def cmd_status(ledger, args) -> int:
    result = ledger.status(project=_project_filter(args.project))
    lines = []
    sources = result["sources"]
    if sources:
        src_line = " · ".join(
            f"{name} {humanize_age(info['last_seen'])} ago" + (f" ({info['actor']})" if info.get("actor") else "")
            for name, info in sources.items()
        )
        lines.append(f"sources: {src_line}")
    lines.append(f"OVERDUE ({len(result['overdue'])})")
    lines += [f"  {_item_line(it)}" for it in result["overdue"]]
    for label, key in (("IN FLIGHT", "inflight"), ("READY", "ready"), ("WAITING", "waiting")):
        lines.append(f"{label} ({len(result[key])})")
        for it in result[key]:
            lines.append(f"  {_item_line(it)}")
            for child in it.get("nested_children") or []:
                lines.append(f"    {_item_line(child)}  ({child['status']})")
    _print(args, result, lines)
    return 0


def _guide_lines(g: dict) -> list[str]:
    actor = g["example_actor"] or "your-actor"
    project = g["example_project"] or "myproject"
    item_id = g["example_item_id"] or "d-xxxx"

    lines = [
        "dori guide - how to use this ledger",
        "",
        "A shared work ledger of item files in items/ and an append-only",
        "journal, synced through git with dori sync.",
        "",
        "Core loop:",
        f'  dori upsert --ref forgejo:123 --title "..." --project {project} '
        f'--source ingest --actor {actor}',
        f"  dori claim {item_id} --actor {actor}",
        f'  dori log "note" --ref {item_id} --actor {actor}',
        f'  dori update {item_id} --status done --log "done, PR merged" --actor {actor}',
        f"  dori release {item_id} --actor {actor}",
        "  dori sync",
        "",
        "Registered prefixes:",
    ]
    if g["prefixes"]:
        for p in g["prefixes"]:
            desc = f"  {p['desc']}" if p.get("desc") else ""
            lines.append(f"  {p['kind']:5} {p['name']:12}{desc}")
    else:
        lines.append("  (none) - run `dori prefix add <name> --kind ref|link|both`")

    lines += [
        "",
        "Statuses:",
        "  idea      captured, no commitment - graduate to ready before claiming",
        "  ready     unclaimed, workable",
        "  inflight  claimed and being worked",
        "  waiting   waiting on something external",
        "  done      finished",
        "  parked    shelved, not currently pursued",
        "  blocked   derived from open deps, never stored - shown as [blocked] in list/status",
        "",
        "Host vs actor:",
        f"  this machine's host id: {g['host_id']}",
        "  pass --actor <name>, one per concurrent agent or session",
    ]

    lines.append("")
    lines.append(f"Tags in use: {', '.join(g['tags']) if g['tags'] else '(none yet)'}")
    lines.append(f"Projects in use: {', '.join(g['projects']) if g['projects'] else '(none yet)'}")
    return lines


def cmd_guide(ledger, args) -> int:
    data = ledger.guide()
    _print(args, data, _guide_lines(data))
    return 0


def cmd_doctor(ledger, args) -> int:
    result = ledger.doctor()
    problems = result["problems"]
    lines = [f"[{p['severity']}:{p['check']}] {p['message']}" for p in problems] or ["ok: no problems found"]
    _print(args, result, lines)
    return 1 if result["has_errors"] else 0


def cmd_prefix(ledger, args) -> int:
    if args.prefix_action == "add":
        result = ledger.prefix_add(args.name, args.kind, desc=args.desc)
        _print(args, result, [f"registered prefix {result['name']} (kind={result['kind']})"])
        return 0
    result = ledger.prefix_list()
    lines = [
        f"{p['name']}  {p['kind']}" + (f"  {p['desc']}" if p.get("desc") else "")
        for p in result
    ] or ["(no prefixes registered)"]
    _print(args, result, lines)
    return 0


def cmd_sync(ledger, args) -> int:
    result = ledger.sync()
    _print(args, result, [result["message"]])
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return cmd_init(args)
        if args.command == "host":
            return cmd_host(args)

        ledger = Ledger(args.dir)
        require_ledger(ledger.data_dir)
        handlers = {
            "upsert": cmd_upsert,
            "log": cmd_log,
            "update": cmd_update,
            "claim": cmd_claim,
            "release": cmd_release,
            "list": cmd_list,
            "show": cmd_show,
            "status": cmd_status,
            "split": cmd_split,
            "guide": cmd_guide,
            "doctor": cmd_doctor,
            "prefix": cmd_prefix,
            "sync": cmd_sync,
        }
        return handlers[args.command](ledger, args)
    except DandoriError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
