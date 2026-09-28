"""dandori core: Ledger, the local-first work ledger for AI agents.

Storage layout under a data dir:
    config.yaml     - prefix registry and sync settings (host identity is
                      machine-local, see machine_host_id)
    items/<id>.md   - one file per item, YAML frontmatter + markdown body
    journal/<host>-YYYY-MM.jsonl - append-only, one file per host per month
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Optional

import yaml

_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_YAML_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


class DandoriError(Exception):
    pass


class ActorRequiredError(DandoriError):
    pass


class ClaimConflictError(DandoriError):
    pass


class ItemNotFoundError(DandoriError):
    pass


class RefConflictError(DandoriError):
    pass


class LockTimeoutError(DandoriError):
    pass


STATUSES = ("idea", "ready", "inflight", "waiting", "done", "parked")

FIELD_ORDER = (
    "id",
    "title",
    "project",
    "status",
    "type",
    "priority",
    "due",
    "refs",
    "links",
    "tags",
    "deps",
    "source",
    "created",
    "updated",
    "claimed_by",
    "claimed_at",
)

PREFIX_KINDS = ("ref", "link", "both")

DEFAULT_PREFIXES = {
    "vikunja": {"kind": "ref", "desc": "Vikunja task"},
    "forgejo": {"kind": "ref", "desc": "Forgejo issue/PR"},
    "jira": {"kind": "ref", "desc": "Jira ticket"},
    "commit": {"kind": "link", "desc": "commit:<repo>@<sha> (bare commit:<sha> allowed)"},
    "pr": {"kind": "link", "desc": "pr:forgejo:<repo>#N or pr:github:<owner>/<repo>#N"},
}

CLAIM_TTL = 4 * 3600
LOCK_TIMEOUT = 10.0
EAGER_SYNC_TIMEOUT = 5.0

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?\n?(.*)\Z", re.DOTALL)
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

LEDGER_PATHS = ("config.yaml", "items", "journal")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime(ISO_FORMAT)


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, ISO_FORMAT).replace(tzinfo=timezone.utc)


def humanize_age(iso_ts: str) -> str:
    n = max(0, int((datetime.now(timezone.utc) - parse_iso(iso_ts)).total_seconds()))
    for unit, size in (("s", 60), ("m", 60), ("h", 24)):
        if n < size:
            return f"{n}{unit}"
        n //= size
    return f"{n}d"


_DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_due(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if not _DUE_RE.match(value):
        raise DandoriError(f"invalid due date {value!r}, expected YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as e:
        raise DandoriError(f"invalid due date {value!r}: {e}") from e
    return value


def validate_status(status: Optional[str]) -> None:
    if status is not None and status not in STATUSES:
        raise DandoriError(f"invalid status {status!r}, must be one of {STATUSES}")


def _flock_acquire(fd: int) -> None:
    deadline = time.monotonic() + LOCK_TIMEOUT
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise LockTimeoutError(f"timed out after {LOCK_TIMEOUT}s waiting for lock file")
            time.sleep(0.05)


@contextmanager
def locked(data_dir: Path):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(data_dir / ".lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        _flock_acquire(fd)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def load_config(data_dir: Path) -> dict:
    path = Path(data_dir) / "config.yaml"
    if not path.exists():
        return {}
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_YAML_LOADER) or {}


def save_config(data_dir: Path, config: dict) -> None:
    path = Path(data_dir) / "config.yaml"
    path.write_text(yaml.dump(config, Dumper=_YAML_DUMPER, sort_keys=False), encoding="utf-8")


def prefix_of(value: str) -> Optional[str]:
    if ":" not in value:
        return None
    return value.split(":", 1)[0]


def load_prefixes(data_dir: Path) -> dict:
    return load_config(data_dir).get("prefixes") or {}


def check_prefix_registered(data_dir: Path, value: str, kind: str) -> None:
    prefix = prefix_of(value)
    if prefix is None:
        return
    prefixes = load_prefixes(data_dir)
    entry = prefixes.get(prefix)
    if entry and entry.get("kind") in (kind, "both"):
        return
    registered = sorted(n for n, e in prefixes.items() if e.get("kind") in (kind, "both"))
    raise DandoriError(
        f"prefix {prefix!r} is not registered for {kind}s; registered {kind} prefixes: "
        f"{', '.join(registered) if registered else '(none)'} - run `dori prefix add {prefix} --kind {kind}`"
    )


def host_config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dandori" / "host"


def save_machine_host_id(host_id: str) -> None:
    path = host_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(host_id + "\n", encoding="utf-8")


def machine_host_id() -> str:
    """$DANDORI_HOST overrides the host file for this process and is never persisted."""
    env_host = os.environ.get("DANDORI_HOST")
    if env_host:
        return env_host
    path = host_config_path()
    existing = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if existing:
        return existing
    derived = socket.gethostname()
    save_machine_host_id(derived)
    return derived


def require_ledger(data_dir: Path) -> None:
    if not (Path(data_dir) / "config.yaml").exists():
        raise DandoriError(f"{data_dir} is not a dandori ledger (no config.yaml) - run `dori init --dir {data_dir}`")


def canonical_frontmatter(fm: dict) -> dict:
    return {k: fm[k] for k in dict.fromkeys((*FIELD_ORDER, *fm)) if fm.get(k) is not None}


def _notes(result: dict, **notes: Optional[str]) -> dict:
    result.update({k: v for k, v in notes.items() if v})
    return result


def render_body(description: Optional[str] = None) -> str:
    return f"## Description\n{description or ''}\n\n## Acceptance criteria\n\n## Notes\n"


_DESCRIPTION_SECTION_RE = re.compile(r"(## Description\n)(.*?)(\n\n## |\Z)", re.DOTALL)


def set_description(body: str, description: str) -> str:
    """No-op when the body has no `## Description` heading (hand-edited bodies)."""
    if not _DESCRIPTION_SECTION_RE.search(body):
        return body
    return _DESCRIPTION_SECTION_RE.sub(
        lambda m: f"{m.group(1)}{description}{m.group(3)}", body, count=1,
    )


def render_item_file(fm: dict, body: str) -> str:
    fm = canonical_frontmatter(fm)
    yaml_text = yaml.dump(fm, Dumper=_YAML_DUMPER, sort_keys=False, default_flow_style=False, allow_unicode=True)
    return f"---\n{yaml_text}---\n\n{body}"


def parse_item_file(path: Path) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not m:
        raise DandoriError(f"malformed item file: {path}")
    return yaml.load(m.group(1), Loader=_YAML_LOADER) or {}, m.group(2)


def generate_id(items_dir: Path) -> str:
    while True:
        candidate = f"d-{secrets.token_hex(3)}"
        if not (items_dir / f"{candidate}.md").exists():
            return candidate


def _normalize_list_field(value):
    if value is None:
        return None
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return list(value)


def _compute_blocked(fm: dict, status_by_id: dict[str, str]) -> tuple[bool, list[str]]:
    blockers = []
    for dep in fm.get("deps") or []:
        if ":" not in dep:
            continue
        dtype, target = dep.split(":", 1)
        if dtype not in ("blocks", "needs"):
            continue
        if status_by_id.get(target, "done") != "done":
            blockers.append(target)
    return (bool(blockers), blockers)


def part_of_parent(fm: dict) -> Optional[str]:
    for dep in fm.get("deps") or []:
        if dep.startswith("part-of:"):
            return dep.split(":", 1)[1]
    return None


def derive_project_from_cwd(cwd: Optional[Path] = None) -> Optional[str]:
    """None outside a git repo. Otherwise the origin remote's repo name, then
    the alphabetically first remote's, then the toplevel directory name."""
    cwd = Path(cwd) if cwd else Path.cwd()
    toplevel = _git(["rev-parse", "--show-toplevel"], cwd)
    if toplevel.returncode != 0:
        return None
    remotes = _git(["remote"], cwd).stdout.split()
    if remotes:
        remote_name = "origin" if "origin" in remotes else sorted(remotes)[0]
        url = _git(["remote", "get-url", remote_name], cwd).stdout.strip().rstrip("/").removesuffix(".git")
        project = re.split(r"[/:]", url)[-1]
        if project:
            return project
    return Path(toplevel.stdout.strip()).name or None


def _refuse_idea_if_claimed(item_id: str, fm: dict, status: Optional[str]) -> None:
    if status == "idea" and fm.get("claimed_by"):
        raise DandoriError(f"{item_id} is claimed by {fm['claimed_by']}; release it before setting status to idea")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _claim_expired(fm: dict) -> bool:
    claimed_at = fm.get("claimed_at")
    if not claimed_at:
        return True
    return (datetime.now(timezone.utc) - parse_iso(claimed_at)).total_seconds() > CLAIM_TTL


def journal_path(journal_dir: Path, host_id: str, when: datetime) -> Path:
    return journal_dir / f"{host_id}-{when:%Y-%m}.jsonl"


def _git(args, cwd: Path, **kw):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, **kw)


def _git_output(args: list[str], cwd: Path):
    return _git(args, cwd, timeout=EAGER_SYNC_TIMEOUT)


def _is_git_repo(data_dir: Path) -> bool:
    """False when data_dir is inside some other repo rather than a repo of its own."""
    toplevel = _git_output(["rev-parse", "--show-toplevel"], data_dir)
    return toplevel.returncode == 0 and Path(toplevel.stdout.strip()).resolve() == Path(data_dir).resolve()


def _short_git_error(stderr: str) -> str:
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return lines[-1] if lines else "unknown git error"


def _rebase_in_progress(data_dir: Path) -> bool:
    for state_dir in ("rebase-merge", "rebase-apply"):
        out = _git_output(["rev-parse", "--git-path", state_dir], data_dir)
        if out.returncode != 0:
            continue
        path = Path(out.stdout.strip())
        if not path.is_absolute():
            path = Path(data_dir) / path
        if path.exists():
            return True
    return False


def _abort_stale_rebase(data_dir: Path) -> None:
    if _rebase_in_progress(data_dir):
        _git_output(["rebase", "--abort"], data_dir)


def _pull_rebase(data_dir: Path, *, timeout: Optional[float] = None):
    """Without --empty=drop a replayed commit that becomes empty stops the rebase."""
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], data_dir, timeout=timeout).stdout.strip()
    fetch = _git(["fetch", "origin", branch], data_dir, timeout=timeout)
    if fetch.returncode != 0:
        return fetch
    return _git(["rebase", "--empty=drop", f"origin/{branch}"], data_dir, timeout=timeout)


def _eager_git_pull(data_dir: Path) -> Optional[str]:
    """Returns None on success, else a short reason string. A failed or
    timed-out pull is rebase-aborted."""
    remotes = _git_output(["remote"], data_dir).stdout.split()
    if "origin" not in remotes:
        return "no origin remote configured"
    _abort_stale_rebase(data_dir)
    try:
        heads = _git_output(["ls-remote", "--heads", "origin"], data_dir)
    except subprocess.TimeoutExpired:
        return "origin unreachable (timeout)"
    if heads.returncode != 0:
        return f"origin unreachable: {_short_git_error(heads.stderr)}"
    if not heads.stdout.strip():
        return None
    try:
        pulled = _pull_rebase(data_dir, timeout=EAGER_SYNC_TIMEOUT)
    except subprocess.TimeoutExpired:
        _abort_stale_rebase(data_dir)
        return "origin unreachable (timeout)"
    if pulled.returncode != 0:
        conflicted = _git_output(["diff", "--name-only", "--diff-filter=U"], data_dir).stdout.split()
        _abort_stale_rebase(data_dir)
        if conflicted:
            return f"pull blocked by conflicts in {', '.join(conflicted)}; resolve with git in {data_dir}"
        return f"pull failed: {_short_git_error(pulled.stderr)}"
    return None


def _eager_stage_and_commit(data_dir: Path, message: str) -> bool:
    """Returns False when there was nothing to commit."""
    add = _git_output(["add", "--", *LEDGER_PATHS], data_dir)
    if add.returncode != 0:
        raise DandoriError(f"git add failed: {_short_git_error(add.stderr)}")
    # `git commit -- items journal` errors when one of those dirs has no
    # tracked or staged content yet.
    staged = _git_output(["diff", "--cached", "--name-only", "--", *LEDGER_PATHS], data_dir).stdout.split()
    if not staged:
        return False
    commit = _git_output(["commit", "-m", message, "--", *staged], data_dir)
    if commit.returncode != 0:
        raise DandoriError(f"git commit failed: {_short_git_error(commit.stderr)}")
    return True


def _eager_push(data_dir: Path) -> Optional[str]:
    """Returns None on success, "rejected" on a non-fast-forward push, else
    a short reason string for any other failure (network, timeout)."""
    try:
        push = _git_output(["push"], data_dir)
    except subprocess.TimeoutExpired:
        return "push timeout"
    if push.returncode == 0:
        return None
    stderr = push.stderr or ""
    if "[rejected]" in stderr or "non-fast-forward" in stderr or "fetch first" in stderr:
        return "rejected"
    return _short_git_error(stderr)


class Ledger:
    def __init__(self, path, actor: Optional[str] = None):
        self.data_dir = Path(path)
        self.items_dir = self.data_dir / "items"
        self.journal_dir = self.data_dir / "journal"
        self.actor = actor

    @classmethod
    def init(cls, path) -> "Ledger":
        ledger = cls(path)
        with locked(ledger.data_dir):
            ledger.items_dir.mkdir(parents=True, exist_ok=True)
            ledger.journal_dir.mkdir(parents=True, exist_ok=True)
            if not (ledger.data_dir / "config.yaml").exists():
                save_config(ledger.data_dir, {"prefixes": DEFAULT_PREFIXES})
            gitignore = ledger.data_dir / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(".lock\n", encoding="utf-8")
        return ledger

    @cached_property
    def host_id(self) -> str:
        return machine_host_id()

    def _lock(self):
        require_ledger(self.data_dir)
        return locked(self.data_dir)

    def _journal_append(self, kind: str, msg: str, ref: Optional[str] = None,
                         actor: Optional[str] = None, source: Optional[str] = None) -> dict:
        entry = {
            "ts": now_iso(),
            "host": self.host_id,
            "actor": actor or self.actor,
            "kind": kind,
            "msg": msg,
            "ref": ref,
        }
        if source:
            entry["source"] = source
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        path = journal_path(self.journal_dir, self.host_id, datetime.now(timezone.utc))
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _read_journal(self) -> list[dict]:
        entries = []
        for p in sorted(self.journal_dir.glob("*.jsonl")):
            with p.open(encoding="utf-8") as f:
                entries += [json.loads(line) for line in f if line.strip()]
        entries.sort(key=lambda e: e["ts"])
        return entries

    def _resolve(self, id_or_ref: str) -> tuple[str, dict, str, Optional[str]]:
        path = self.items_dir / f"{id_or_ref}.md"
        if "/" not in id_or_ref and path.exists():
            fm, body = parse_item_file(path)
            return fm["id"], fm, body, None
        return self._resolve_from_index(id_or_ref, *self._load_index())

    @staticmethod
    def _pick_oldest(id_or_ref: str, matches: list[tuple[str, dict, str]]) -> tuple[str, dict, str, Optional[str]]:
        """When a ref matches several items, returns the oldest by created
        plus a warning pointing at `dori doctor`."""
        if not matches:
            raise ItemNotFoundError(f"no item found for '{id_or_ref}'")
        matches.sort(key=lambda m: m[1]["created"])
        warning = None
        if len(matches) > 1:
            ids = [m[0] for m in matches]
            warning = (f"ref {id_or_ref!r} matches multiple items ({', '.join(ids)}); "
                       f"using oldest {ids[0]}, run `dori doctor` to fix")
        item_id, fm, body = matches[0]
        return item_id, fm, body, warning

    def _load_index(self) -> tuple[dict[str, tuple[dict, str]], dict[str, list[str]]]:
        """items_by_id maps item id -> (fm, body); ids_by_ref maps a ref to
        every item id holding it (more than one only after an offline merge)."""
        items_by_id: dict[str, tuple[dict, str]] = {}
        ids_by_ref: dict[str, list[str]] = {}
        for p in sorted(self.items_dir.glob("*.md")):
            fm, body = parse_item_file(p)
            items_by_id[fm["id"]] = (fm, body)
            for r in fm.get("refs") or []:
                ids_by_ref.setdefault(r, []).append(fm["id"])
        return items_by_id, ids_by_ref

    def _resolve_from_index(
        self, id_or_ref: str,
        items_by_id: dict[str, tuple[dict, str]], ids_by_ref: dict[str, list[str]],
    ) -> tuple[str, dict, str, Optional[str]]:
        if "/" not in id_or_ref and id_or_ref in items_by_id:
            ids = [id_or_ref]
        else:
            ids = ids_by_ref.get(id_or_ref) or []
        return self._pick_oldest(id_or_ref, [(iid, *items_by_id[iid]) for iid in ids])

    def _write_item(self, item_id: str, fm: dict, body: str) -> None:
        fm["updated"] = now_iso()
        path = self.items_dir / f"{item_id}.md"
        path.write_text(render_item_file(fm, body), encoding="utf-8")

    def _journal_status(self, item_id: str, before: Optional[str], after: str,
                        actor: Optional[str]) -> None:
        if after != before:
            self._journal_append("status", f"status: {before} -> {after}", ref=item_id, actor=actor)

    def _eager_start(self, sync: Optional[bool], verb: str) -> tuple[bool, Optional[str]]:
        """Commits pending changes and pulls. eager is False when config or
        --no-sync disables sync, or when origin is unreachable."""
        if sync is None:
            sync = bool((load_config(self.data_dir).get("sync") or {}).get("eager_claims", True))
        if not sync:
            return False, None
        if not _is_git_repo(self.data_dir):
            reason = "data dir is not a git repo"
        else:
            _abort_stale_rebase(self.data_dir)
            _eager_stage_and_commit(self.data_dir, "pending changes")
            reason = _eager_git_pull(self.data_dir)
        if reason:
            return False, f"{verb} is local-only until next sync ({reason})"
        return True, None

    def upsert(self, data, *, source: str, actor: Optional[str] = None,
               sync: bool = False, force: bool = False):
        """Upsert one item (dict) or a batch (list of dicts), keyed by ref."""
        batch = isinstance(data, list)
        payload = data if batch else [data]
        results = []
        with self._lock():
            self.items_dir.mkdir(parents=True, exist_ok=True)
            self._journal_append("ingest", f"ingest from {source}: {len(payload)} items",
                                 actor=actor, source=source)
            items_by_id, ids_by_ref = self._load_index()
            for item_data in payload:
                results.append(self._upsert_one(
                    item_data, source=source, actor=actor, force=force,
                    items_by_id=items_by_id, ids_by_ref=ids_by_ref,
                ))
        if sync:
            self.sync()
        return results if batch else results[0]

    def _upsert_one(
        self, data: dict, *, source: str, actor: Optional[str],
        items_by_id: dict[str, tuple[dict, str]], ids_by_ref: dict[str, list[str]],
        force: bool = False,
    ) -> dict:
        data = dict(data)
        validate_status(data.get("status"))
        for key in ("tags", "deps"):
            if key in data:
                data[key] = _normalize_list_field(data[key])
        refs = data.pop("refs", None) or []
        if isinstance(refs, str):
            refs = [refs]
        single_ref = data.pop("ref", None)
        if single_ref:
            refs = list(dict.fromkeys(refs + [single_ref]))
        new_links = _normalize_list_field(data.pop("links", None)) or []

        for r in refs:
            check_prefix_registered(self.data_dir, r, "ref")
        for link in new_links:
            check_prefix_registered(self.data_dir, link, "link")

        target = None
        ref_warning = None
        for r in refs:
            try:
                iid, fm, body, warning = self._resolve_from_index(r, items_by_id, ids_by_ref)
            except ItemNotFoundError:
                continue
            if target is None:
                target = (iid, fm, body)
            elif iid != target[0]:
                raise RefConflictError(f"ref {r!r} already belongs to {iid}")
            ref_warning = ref_warning or warning

        if target:
            item_id, fm, body = target
            _refuse_idea_if_claimed(item_id, fm, data.get("status"))
            before, before_body = dict(fm), body
            new_refs = [r for r in refs if r != item_id]
            fm["refs"] = list(dict.fromkeys((fm.get("refs") or []) + new_refs))
            if new_links:
                fm["links"] = list(dict.fromkeys((fm.get("links") or []) + new_links))

            current_source = fm.get("source")
            has_authority = force or current_source is None or source == current_source
            source_note = None
            if data.get("title") is not None or data.get("description") is not None:
                if has_authority:
                    if data.get("title") is not None:
                        fm["title"] = data["title"]
                    if data.get("description") is not None:
                        body = set_description(body, data["description"])
                else:
                    source_note = (
                        f"{current_source!r} owns title/description for {item_id}; "
                        f"--source {source!r} did not change them (--force overrides)"
                    )

            for key in ("project", "status", "type", "priority", "tags", "deps"):
                if data.get(key) is not None:
                    fm[key] = data[key]
            if data.get("due") is not None:
                fm["due"] = validate_due(data["due"])
            if has_authority:
                fm["source"] = source

            if any(before.get(k) != v for k, v in fm.items()) or body != before_body:
                self._write_item(item_id, fm, body)
            items_by_id[item_id] = (fm, body)
            for r in new_refs:
                ids = ids_by_ref.setdefault(r, [])
                if item_id not in ids:
                    ids.append(item_id)
            self._journal_status(item_id, before.get("status"), fm["status"], actor)
            return _notes(canonical_frontmatter(fm), ref_warning=ref_warning, source_note=source_note)

        now = now_iso()
        title = data.get("title") or (refs[0] if refs else "untitled")
        item_id = generate_id(self.items_dir)
        project = data.get("project")
        if project is None and not data.get("no_project"):
            project = derive_project_from_cwd()
        fm = {
            "id": item_id,
            "title": title,
            "project": project,
            "status": data.get("status") or "ready",
            "type": data.get("type") or "task",
            "priority": data.get("priority") if data.get("priority") is not None else 2,
            "due": validate_due(data.get("due")),
            "refs": list(dict.fromkeys(refs)),
            "links": list(dict.fromkeys(new_links)),
            "tags": data.get("tags") or [],
            "deps": data.get("deps") or [],
            "source": source,
            "created": now,
            "updated": now,
        }
        body = render_body(data.get("description"))
        self._write_item(item_id, fm, body)
        items_by_id[item_id] = (fm, body)
        for r in fm["refs"]:
            ids_by_ref.setdefault(r, []).append(item_id)
        self._journal_append("create", f"created: {fm['title']}", ref=item_id, actor=actor)
        return canonical_frontmatter(fm)

    def update(self, id_or_ref: str, *, actor: Optional[str] = None, log: Optional[str] = None,
               sync: bool = False, **fields) -> dict:
        validate_status(fields.get("status"))
        with self._lock():
            item_id, fm, body, ref_warning = self._resolve(id_or_ref)
            _refuse_idea_if_claimed(item_id, fm, fields.get("status"))
            before = dict(fm)
            for key, value in fields.items():
                if value is None:
                    continue
                if key == "due":
                    value = validate_due(value)
                elif key == "project" and value == "":
                    value = None
                fm[key] = value
            if any(before.get(k) != v for k, v in fm.items()):
                self._write_item(item_id, fm, body)
                self._journal_status(item_id, before.get("status"), fm["status"], actor)
            if log:
                self._journal_append("log", log, ref=item_id, actor=actor)
            result = _notes(canonical_frontmatter(fm), ref_warning=ref_warning)
        if sync:
            self.sync()
        return result

    def log(self, msg: str, *, ref: Optional[str] = None, actor: Optional[str] = None,
            sync: bool = False) -> dict:
        ref_warning = None
        with self._lock():
            if ref:
                ref, _, _, ref_warning = self._resolve(ref)
            entry = self._journal_append("log", msg, ref=ref, actor=actor)
        if sync:
            self.sync()
        return _notes(entry, ref_warning=ref_warning)

    def claim(self, id_or_ref: str, actor: Optional[str], log: Optional[str] = None,
              sync: Optional[bool] = None) -> dict:
        if not actor:
            raise ActorRequiredError("claim requires an actor")
        with self._lock():
            eager, warning = self._eager_start(sync, "claim")
            if eager:
                base = _git_output(["rev-parse", "HEAD"], self.data_dir).stdout.strip()

            item_id, fm, body, ref_warning = self._resolve(id_or_ref)
            if fm.get("status") == "idea":
                raise DandoriError(f"{item_id} is an idea; graduate it to ready first")
            current = fm.get("claimed_by")
            if current and current != actor and not _claim_expired(fm):
                raise ClaimConflictError(f"already claimed by {current}")
            before_status = fm.get("status")
            fm["claimed_by"] = actor
            fm["claimed_at"] = now_iso()
            if before_status == "ready":
                fm["status"] = "inflight"
            self._write_item(item_id, fm, body)
            verb = "re-claimed" if current == actor else "claimed"
            self._journal_append("claim", f"{verb} by {actor}", ref=item_id, actor=actor)
            self._journal_status(item_id, before_status, fm["status"], actor)
            if log:
                self._journal_append("log", log, ref=item_id, actor=actor)

            if eager:
                _eager_stage_and_commit(self.data_dir, f"claim {item_id} by {actor}")
                push_result = _eager_push(self.data_dir)
                if push_result == "rejected":
                    _git_output(["reset", "--hard", base], self.data_dir)
                    _eager_git_pull(self.data_dir)
                    winner = self._resolve(id_or_ref)[1].get("claimed_by") or "unknown"
                    raise ClaimConflictError(f"claim lost to {winner}")
                elif push_result:
                    warning = f"claim is local-only until next sync ({push_result})"

            return _notes(canonical_frontmatter(fm), sync_warning=warning, ref_warning=ref_warning)

    def release(self, id_or_ref: str, actor: Optional[str], log: Optional[str] = None,
                sync: Optional[bool] = None) -> dict:
        if not actor:
            raise ActorRequiredError("release requires an actor")
        with self._lock():
            eager, warning = self._eager_start(sync, "release")
            item_id, fm, body, ref_warning = self._resolve(id_or_ref)
            current = fm.get("claimed_by")
            if current and current != actor and not _claim_expired(fm):
                raise ClaimConflictError(f"claimed by {current}, not {actor}")
            had_claim = bool(current)
            before_status = fm.get("status")
            fm.pop("claimed_by", None)
            fm.pop("claimed_at", None)
            if had_claim and before_status == "inflight":
                fm["status"] = "ready"
            self._write_item(item_id, fm, body)
            msg = f"released by {actor}" if had_claim else f"release no-op by {actor}"
            self._journal_append("release", msg, ref=item_id, actor=actor)
            self._journal_status(item_id, before_status, fm["status"], actor)
            if log:
                self._journal_append("log", log, ref=item_id, actor=actor)

            if eager and _eager_stage_and_commit(self.data_dir, f"release {item_id} by {actor}"):
                push_result = _eager_push(self.data_dir)
                if push_result == "rejected":
                    push_result = _eager_git_pull(self.data_dir) or _eager_push(self.data_dir)
                if push_result:
                    warning = f"release is local-only until next sync ({push_result})"

            return _notes(canonical_frontmatter(fm), sync_warning=warning, ref_warning=ref_warning)

    def items(self, *, status: Optional[str] = None, project: Optional[str] = None) -> list[dict]:
        all_items = [parse_item_file(p)[0] for p in sorted(self.items_dir.glob("*.md"))]
        status_by_id = {it["id"]: it["status"] for it in all_items}
        children_by_parent: dict[str, list[str]] = {}
        for it in all_items:
            parent_id = part_of_parent(it)
            if parent_id:
                children_by_parent.setdefault(parent_id, []).append(it["id"])
        results = []
        for fm in all_items:
            if status and fm.get("status") != status:
                continue
            if project and fm.get("project") != project:
                continue
            children_ids = children_by_parent.get(fm["id"])
            fm = canonical_frontmatter(fm)
            fm["blocked"], fm["blocked_by"] = _compute_blocked(fm, status_by_id)
            fm["claim_expired"] = _claim_expired(fm) if fm.get("claimed_by") else False
            if children_ids:
                fm["children"] = children_ids
                fm["children_done"] = sum(1 for c in children_ids if status_by_id.get(c) == "done")
            results.append(fm)
        return results

    def show(self, id_or_ref: str) -> dict:
        item_id, _, body, ref_warning = self._resolve(id_or_ref)
        by_id = {it["id"]: it for it in self.items()}
        fm = by_id[item_id]
        children = [by_id[c] for c in fm.get("children", []) if c in by_id]
        journal = [e for e in self._read_journal() if e.get("ref") == item_id]
        return _notes({"item": fm, "body": body, "journal": journal, "children": children},
                      ref_warning=ref_warning)

    def split(self, parent_id_or_ref: str, titles: list[str], *,
              actor: Optional[str] = None, source: Optional[str] = None) -> dict:
        if not titles:
            raise DandoriError("split requires at least one child title")
        with self._lock():
            parent_id, parent_fm, parent_body, ref_warning = self._resolve(parent_id_or_ref)
            child_source = source or parent_fm.get("source") or "split"
            deps = list(parent_fm.get("deps") or [])
            children = []
            items_by_id, ids_by_ref = self._load_index()
            for title in titles:
                child = self._upsert_one(
                    {"title": title, "project": parent_fm.get("project"),
                     "deps": [f"part-of:{parent_id}"]},
                    source=child_source, actor=actor,
                    items_by_id=items_by_id, ids_by_ref=ids_by_ref,
                )
                children.append(child)
                deps.append(f"needs:{child['id']}")
            parent_fm["deps"] = list(dict.fromkeys(deps))
            self._write_item(parent_id, parent_fm, parent_body)
            titles_str = ", ".join(c["title"] for c in children)
            self._journal_append(
                "split", f"split into {len(children)} children: {titles_str}",
                ref=parent_id, actor=actor,
            )
            return _notes({"parent": canonical_frontmatter(parent_fm), "children": children},
                          ref_warning=ref_warning)

    def status(self, project: Optional[str] = None) -> dict:
        all_items = self.items(project=project)
        by_id = {it["id"]: it for it in all_items}
        buckets: dict[str, list[dict]] = {"inflight": [], "ready": [], "waiting": []}
        today = datetime.now(timezone.utc).date().isoformat()
        overdue = []

        nested_ids = {c for it in all_items if it["status"] in buckets for c in it.get("children", [])}
        for it in all_items:
            if it["status"] in buckets and it["id"] not in nested_ids:
                if it.get("children"):
                    it = {**it, "nested_children": [by_id[c] for c in it["children"] if c in by_id]}
                buckets[it["status"]].append(it)
            if it.get("due") and it["due"] < today and it["status"] not in ("done", "parked", "idea"):
                overdue.append(it)
        overdue.sort(key=lambda it: it["due"])
        buckets["ready"].sort(key=lambda it: (it.get("due") is None, it.get("due") or "", it.get("priority", 2)))
        sources = {}
        for e in self._read_journal():
            if e["kind"] == "ingest":
                sources[e["source"]] = {"last_seen": e["ts"], "actor": e.get("actor")}
        return {
            "sources": dict(sorted(sources.items())),
            "overdue": overdue,
            "inflight": buckets["inflight"],
            "ready": buckets["ready"],
            "waiting": buckets["waiting"],
        }

    def doctor(self) -> dict:
        all_items = self.items()
        id_set = {it["id"] for it in all_items}
        problems = []

        prefixes = load_prefixes(self.data_dir)
        for it in all_items:
            for kind, values in (("ref", it.get("refs") or []), ("link", it.get("links") or [])):
                for value in values:
                    p = prefix_of(value)
                    if p and p not in prefixes:
                        problems.append({
                            "check": "unregistered_prefix",
                            "severity": "info",
                            "item": it["id"],
                            "kind": kind,
                            "value": value,
                            "message": f"{it['id']} {kind} {value!r} uses unregistered prefix {p!r}",
                        })

        ref_to_ids: dict[str, list[str]] = {}
        for it in all_items:
            for r in it.get("refs") or []:
                ref_to_ids.setdefault(r, []).append(it["id"])
        for ref, ids in sorted(ref_to_ids.items()):
            if len(ids) > 1:
                problems.append({
                    "check": "duplicate_ref",
                    "severity": "error",
                    "ref": ref,
                    "items": sorted(ids),
                    "message": f"ref {ref!r} is held by multiple items: {', '.join(sorted(ids))}",
                })

        for it in all_items:
            if it["claim_expired"]:
                problems.append({
                    "check": "expired_claim",
                    "severity": "info",
                    "item": it["id"],
                    "message": f"{it['id']} claimed by {it['claimed_by']} but claim expired",
                })

        for it in all_items:
            if it.get("status") == "idea" and it.get("claimed_by"):
                problems.append({
                    "check": "claimed_idea",
                    "severity": "error",
                    "item": it["id"],
                    "message": f"{it['id']} is status idea but claimed by {it['claimed_by']}; "
                               "release it or graduate it to ready",
                })

        for it in all_items:
            for dep in it.get("deps") or []:
                if ":" not in dep:
                    continue
                dtype, target = dep.split(":", 1)
                if dtype in ("part-of", "needs") and target not in id_set:
                    problems.append({
                        "check": "dangling_dep",
                        "severity": "error",
                        "item": it["id"],
                        "dep": dep,
                        "message": f"{it['id']} has {dtype}:{target} but {target} does not exist",
                    })

        for it in all_items:
            if isinstance(it.get("tags"), str):
                problems.append({
                    "check": "string_tags",
                    "severity": "error",
                    "item": it["id"],
                    "message": f"{it['id']} tags is a string, not a list ({it['tags']!r}); "
                               f"re-tag with `dori update {it['id']} --tags ...`",
                })

        for e in self._read_journal():
            if e["kind"] == "log" and e.get("ref") and e["ref"] not in id_set:
                problems.append({
                    "check": "orphaned_log_ref",
                    "severity": "info",
                    "ref": e["ref"],
                    "ts": e["ts"],
                    "message": f"log entry at {e['ts']} has ref {e['ref']!r}, not an item id; "
                               "`dori show` does not list it",
                })

        return {
            "problems": problems,
            "clean": not problems,
            "has_errors": any(p["severity"] == "error" for p in problems),
        }

    def prefix_add(self, name: str, kind: str, desc: Optional[str] = None,
                    *, actor: Optional[str] = None) -> dict:
        if kind not in PREFIX_KINDS:
            raise DandoriError(f"invalid prefix kind {kind!r}, must be one of {PREFIX_KINDS}")
        with self._lock():
            config = load_config(self.data_dir)
            prefixes = config.get("prefixes") or {}
            entry = {"kind": kind}
            if desc:
                entry["desc"] = desc
            prefixes[name] = entry
            config["prefixes"] = prefixes
            save_config(self.data_dir, config)
            self._journal_append("prefix", f"prefix added: {name} (kind={kind})", actor=actor)
        return {"name": name, **entry}

    def prefix_list(self) -> list[dict]:
        prefixes = load_prefixes(self.data_dir)
        return [{"name": name, **entry} for name, entry in sorted(prefixes.items())]

    def guide(self) -> dict:
        all_items = self.items()
        journal = self._read_journal()
        example_actor = next(
            (e["actor"] for e in reversed(journal) if e.get("actor")), self.actor,
        )
        example_item = all_items[0] if all_items else None
        return {
            "host_id": self.host_id,
            "prefixes": self.prefix_list(),
            "projects": sorted({it["project"] for it in all_items if it.get("project")}),
            "tags": sorted({t for it in all_items for t in (it.get("tags") or [])}),
            "example_actor": example_actor,
            "example_project": example_item.get("project") if example_item else None,
            "example_item_id": example_item["id"] if example_item else None,
        }

    def sync(self) -> dict:
        def git(*args: str):
            return _git(args, self.data_dir, check=True)

        require_ledger(self.data_dir)
        try:
            if not _is_git_repo(self.data_dir):
                git("init")
            _abort_stale_rebase(self.data_dir)
            committed = _eager_stage_and_commit(self.data_dir, "dori sync")
            if "origin" not in git("remote").stdout.split():
                msg = "committed locally; no origin remote configured" if committed else "no changes; no origin remote configured"
                return {"committed": committed, "pushed": False, "message": msg}
            branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            if not git("ls-remote", "--heads", "origin").stdout.strip():
                git("push", "-u", "origin", branch)
                return {"committed": committed, "pushed": True, "message": "pushed initial commit to empty origin"}

            def changed_items(*revs: str) -> int:
                return len(git("diff", "--name-only", *revs, "--", "items").stdout.split())

            head = git("rev-parse", "HEAD").stdout.strip()
            pulled = _pull_rebase(self.data_dir)
            if pulled.returncode != 0:
                conflicted = git("diff", "--name-only", "--diff-filter=U").stdout.split()
                _abort_stale_rebase(self.data_dir)
                if not conflicted:
                    raise DandoriError(f"sync: {_short_git_error(pulled.stderr)}")
                raise DandoriError(
                    f"sync: conflicts in {', '.join(conflicted)}; resolve with git in "
                    f"{self.data_dir}, then rerun `dori sync`"
                )
            pulled_items = changed_items(f"{head}...origin/{branch}")
            pushed_items = changed_items(f"origin/{branch}", "HEAD")
            git("push")
            return {
                "committed": committed, "pushed": True,
                "pulled_items": pulled_items, "pushed_items": pushed_items,
                "message": f"synced with origin: pulled {_count(pulled_items, 'item')}, "
                           f"pushed {_count(pushed_items, 'item')}",
            }
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            raise DandoriError(f"sync: {stderr or e}") from e
