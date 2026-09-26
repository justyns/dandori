# dandori (`dori`)

A local-first, git-syncable ledger of work items and an activity journal.
Agents ingest from Jira, Vikunja, Forgejo, or wherever, and stay responsible
for freshness. dandori stores, dedups, and queries, as a library
(`from dandori import Ledger`) and a thin CLI (`dori`).

Storage is `items/<id>.md` (YAML frontmatter + markdown body) and an
append-only `journal/<host>-YYYY-MM.jsonl` in a plain git repo, synced with
`git push`/`pull`. There is no daemon and no credential store.

## Install

```
uv tool install /path/to/dandori
export DORI_DIR=~/dandori
dori init
```

`--dir` after the subcommand overrides `$DORI_DIR`. Every command except
`init` and `host` refuses a dir with no `config.yaml`, and every command
takes `--json` for `{"schema_version": 1, "data": ...}`.

## Example

```
$ echo '[{"ref": "forgejo:tsugite#868", "title": "Mobile chat density", "status": "ready", "type": "bug", "priority": 2, "tags": ["tsugite", "ui"]}]' \
  | dori upsert --stdin-json --source forgejo --actor alice
d-e43b31  Mobile chat density (bug, p2)  [tsugite]

$ dori claim d-e43b31 --actor laptop-cc
claimed d-e43b31 for laptop-cc

$ dori log "root cause is PaneView.svelte:77, PR up as tsugite#871" --ref d-e43b31 --actor laptop-cc
logged: root cause is PaneView.svelte:77, PR up as tsugite#871

$ dori status
sources: forgejo 1s ago (alice)
OVERDUE (0)
IN FLIGHT (1)
  d-e43b31  Mobile chat density (bug, p2)  [tsugite]  claimed laptop-cc, 1s
READY (0)
WAITING (0)

$ dori update d-e43b31 --status done --log "PR merged" --actor laptop-cc
d-e43b31  Mobile chat density (bug, p2)  [tsugite]  claimed laptop-cc, 1s
logged: PR merged

$ dori release d-e43b31 --actor laptop-cc
released d-e43b31

$ dori sync
synced with origin

$ dori show d-e43b31
d-e43b31  Mobile chat density (bug, p2)  [tsugite]
tags: tsugite, ui

## Description
...

journal:
  2026-09-15T03:42:27Z alice [create] created: Mobile chat density
  2026-09-15T03:42:27Z laptop-cc [claim] claimed by laptop-cc
  2026-09-15T03:42:27Z laptop-cc [status] status: ready -> inflight
  2026-09-15T03:42:27Z laptop-cc [log] root cause is PaneView.svelte:77, PR up as tsugite#871
  2026-09-15T03:42:28Z laptop-cc [status] status: inflight -> done
  2026-09-15T03:42:28Z laptop-cc [log] PR merged
  2026-09-15T03:42:28Z laptop-cc [release] released by laptop-cc
```

## Items

- `refs` identify an item in external systems (`forgejo:tsugite#868`,
  `jira:ABC-123`). A ref belongs to at most one item, re-upserting a ref
  updates that item in place, and `--ref` is repeatable.
- `links` are annotations (`pr:...`, `commit:...`) and may repeat across
  items. `upsert --links` merges them in.
- Every ref and link prefix must be registered: `dori prefix add|list`.
  `init` seeds `vikunja`, `forgejo`, `jira`, `commit`, `pr`.
- `title` and description belong to the item's `source`, set on create and
  taken over by a `--force` upsert. An upsert from another source keeps them
  and prints a note.
- `project` is derived from the cwd's git remote on create. `--project X`
  sets it on `upsert` or `update`, `update --no-project` clears it, and
  `upsert --no-project` skips the derivation. `list` and `status` filter
  with `--project`.
- `--status idea` marks a thought with no commitment. `status` leaves ideas
  out and `claim` refuses them. `--due YYYY-MM-DD` shows in `list` and
  `show` and feeds the OVERDUE section; `--due ""` clears it.
- `dori split <parent> "child" ...` creates `part-of` children and
  `needs:` deps on the parent. Open `blocks:` or `needs:` deps derive
  `[blocked]`, never a stored status, and `list`/`status` nest children
  under their parent.
- `dori log "msg" --ref <id> --actor A` appends a journal line; `--log MSG`
  on `update`, `claim`, and `release` journals one with the transition.
- `show` prints an item with its journal lines and `guide` a brief for an
  agent new to the ledger. `doctor` reports duplicate refs, expired claims,
  claimed-idea items, dangling deps, unregistered prefixes, and
  string-valued tags. Expired claims and unregistered prefixes are
  informational; any other finding makes it exit 1.

## Claims and sync

`claim` moves a `ready` item to `inflight` and `release` moves it back.
Claims expire after 4 hours. `claim` and `release` sync eagerly. When the
data dir is its own git repo with a reachable `origin`, they commit pending
writes, pull with rebase, then write, commit, and push. A claim that loses
the push race fails with `claim lost to <actor>`. Otherwise they stay
local-only and warn. `sync.eager_claims: false` in `config.yaml` turns this
off and `--no-sync` skips it for one call. On other writes `--sync` runs
`dori sync` afterwards; on `claim`/`release` it forces the eager pull and push.

`dori sync` commits, pulls with rebase, and pushes. A conflicting pull is
aborted and reported with the file names. Resolve it with git and rerun.

## Hosts and actors

One machine is one `host_id`, the sole writer of its journal files. It is
stored at `~/.config/dandori/host` and derived from the hostname on first
run. `dori host` shows it, `dori host set X` changes it, and `$DANDORI_HOST`
overrides it for one process. Each concurrent agent on a machine passes its
own `--actor`, and claims conflict on actor.

## Claude Code plugin

The repo is a plugin with two hooks. SessionStart prints `dori guide` and
in-flight items into context. Stop refuses to
end a turn while an item claimed on this host has nothing logged since the
claim. Both need `dori` on PATH and `DORI_DIR` set. The repo is its own
marketplace:

```
/plugin marketplace add <this repo's git url>
/plugin install dandori@dandori
```

To try it from a checkout first, `claude --plugin-dir /path/to/dandori`.

## fzf board

`contrib/dori-fzf` is an interactive board over the `dori` CLI. Requires [fzf](https://github.com/junegunn/fzf). Run it from the
ledger directory or set `DORI_DIR`; `DORI_ACTOR` sets the actor for writes
(default `$USER`). Creating items with ctrl-n needs a registered capture
prefix: `dori prefix add adhoc --kind ref`. Keybinds are listed in the header.

## Publishing

Before pushing to a public remote, run the maintainer's privacy scan (kept
outside this repo). The `LICENSE` copyright line is the one expected hit.
