#!/usr/bin/env python3
"""Works out *what* to build for a content workspace.

A workspace is a directory with content/meta.yaml:

    dictionaries:            # local dictionaries: content/<id>/
      - sahitya
    sources:                 # optional: dictionaries maintained in other repos
      - name: repoA          # checkout dir: <workspace>/external/repoA
        repo: https://github.com/<user>/repoA.git
        ref: main            # optional; default = the repo's default branch
        manifest: dict/meta.yaml   # optional; this is the default
        suffix: -repoA-Nick  # optional; default "-<name>". id = <dir> + suffix
        dictionaries: [kavya]      # optional; only used if the manifest is missing
        defaults:            # optional meta for dictionaries with no meta.yaml
          type: notes

The source's manifest uses the same format as content/meta.yaml
('dictionaries:' list, relative to the manifest's own directory), so the
source repo decides what it offers and how it is laid out. Any 'sources:'
in a source's manifest is ignored (no nesting).

Subcommands:
    plan.py fetch --workspace W   clone/update every source (latest of ref)
    plan.py list  --workspace W   print "<id>\\t<dir>\\t<meta-defaults-json>" lines
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from errors import DictionaryBuildError
from utils import KNOWN_TYPES

ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
DEFAULT_MANIFEST = "dict/meta.yaml"
SOURCE_KEYS = {"name", "repo", "ref", "manifest", "suffix", "dictionaries", "defaults"}


def _read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise DictionaryBuildError("expected a mapping at the top level", file=path)
    return data


def _string_list(value, what, path) -> list:
    if not isinstance(value, list) or not value:
        raise DictionaryBuildError(f"'{what}' must be a non-empty list", file=path)
    return [str(v).strip() for v in value]


def load_workspace_config(content_dir: Path) -> dict:
    """Parses and validates content/meta.yaml.
    Returns {'dictionaries': [...], 'sources': [ {...normalized...} ]}."""
    meta_path = content_dir / "meta.yaml"
    if not meta_path.exists():
        raise DictionaryBuildError("missing top-level meta.yaml", file=content_dir)
    raw = _read_yaml(meta_path)

    local = raw.get("dictionaries") or []
    if local:
        local = _string_list(local, "dictionaries", meta_path)

    sources = []
    for i, src in enumerate(raw.get("sources") or []):
        where = f"sources[{i}]"
        if not isinstance(src, dict):
            raise DictionaryBuildError(f"{where} must be a mapping", file=meta_path)
        unknown = set(src) - SOURCE_KEYS
        if unknown:
            raise DictionaryBuildError(f"{where}: unknown keys {sorted(unknown)}", file=meta_path)
        name = str(src.get("name", "")).strip()
        if not ID_RE.match(name):
            raise DictionaryBuildError(f"{where}: 'name' must match {ID_RE.pattern}", file=meta_path)
        if not src.get("repo"):
            raise DictionaryBuildError(f"{where} ({name}): 'repo' is required", file=meta_path)
        defaults = src.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise DictionaryBuildError(f"{where} ({name}): 'defaults' must be a mapping", file=meta_path)
        if defaults.get("type") is not None and defaults["type"] not in KNOWN_TYPES:
            raise DictionaryBuildError(
                f"{where} ({name}): unknown default type '{defaults['type']}'", file=meta_path)
        sources.append({
            "name": name,
            "repo": str(src["repo"]),
            "ref": str(src["ref"]) if src.get("ref") else None,
            "manifest": str(src.get("manifest") or DEFAULT_MANIFEST),
            "suffix": str(src.get("suffix") if src.get("suffix") is not None else f"-{name}"),
            "dictionaries": (_string_list(src["dictionaries"], f"{where}.dictionaries", meta_path)
                             if src.get("dictionaries") else None),
            "defaults": defaults,
        })

    names = [s["name"] for s in sources]
    if len(set(names)) != len(names):
        raise DictionaryBuildError("duplicate source names", file=meta_path)
    if not local and not sources:
        raise DictionaryBuildError("meta.yaml must define 'dictionaries' and/or 'sources'",
                                   file=meta_path)
    return {"dictionaries": local, "sources": sources, "path": meta_path}


def build_plan(content_dir: Path, external_dir: Path) -> list:
    """Returns [{'id', 'dir', 'meta_defaults', 'source'}] for every
    dictionary to build, local ones first, in config order."""
    cfg = load_workspace_config(content_dir)
    plan = []

    for name in cfg["dictionaries"]:
        d = content_dir / name
        if not (d / "meta.yaml").exists():
            raise DictionaryBuildError(f"dictionary '{name}' has no {name}/meta.yaml",
                                       file=cfg["path"])
        plan.append({"id": name, "dir": d, "meta_defaults": None, "source": None})

    for src in cfg["sources"]:
        root = external_dir / src["name"]
        if not root.is_dir():
            raise DictionaryBuildError(
                f"source '{src['name']}' has not been fetched (expected {root}); "
                "run 'plan.py fetch' first", file=cfg["path"])
        manifest = root / src["manifest"]
        if manifest.exists():
            dict_names = _string_list(_read_yaml(manifest).get("dictionaries"),
                                      "dictionaries", manifest)
        elif src["dictionaries"]:
            dict_names = src["dictionaries"]
        else:
            raise DictionaryBuildError(
                f"source '{src['name']}' has no manifest at '{src['manifest']}' and no "
                "'dictionaries' fallback list", file=cfg["path"])

        base = manifest.parent
        for dname in dict_names:
            d = (base / dname).resolve()
            if not d.is_dir() or root.resolve() not in d.parents:
                raise DictionaryBuildError(
                    f"source '{src['name']}': dictionary '{dname}' is not a directory "
                    f"inside the source", file=manifest if manifest.exists() else cfg["path"])
            dict_id = Path(dname).name + src["suffix"]
            defaults = dict(src["defaults"])
            defaults.setdefault("name", dict_id)
            plan.append({"id": dict_id, "dir": d, "meta_defaults": defaults,
                         "source": src["name"]})

    for entry in plan:
        if not ID_RE.match(entry["id"]):
            raise DictionaryBuildError(f"bad dictionary id '{entry['id']}' "
                                       f"(must match {ID_RE.pattern})", file=cfg["path"])
    ids = [e["id"] for e in plan]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise DictionaryBuildError(f"duplicate dictionary ids: {dupes}", file=cfg["path"])
    return plan


def _git(*args, cwd=None) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        raise DictionaryBuildError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def fetch_sources(content_dir: Path, external_dir: Path) -> list:
    """Shallow-clones/updates every source to the latest commit of its ref.
    Returns [(name, repo, sha)]."""
    cfg = load_workspace_config(content_dir)
    fetched = []
    for src in cfg["sources"]:
        dest = external_dir / src["name"]
        ref = src["ref"] or "HEAD"
        if not (dest / ".git").exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            _git("init", "-q", str(dest))
            _git("remote", "add", "origin", src["repo"], cwd=dest)
        else:
            _git("remote", "set-url", "origin", src["repo"], cwd=dest)
        _git("fetch", "-q", "--depth=1", "origin", ref, cwd=dest)
        _git("checkout", "-q", "--force", "--detach", "FETCH_HEAD", cwd=dest)
        _git("clean", "-q", "-fdx", cwd=dest)
        sha = _git("rev-parse", "HEAD", cwd=dest)
        print(f"Fetched {src['name']} ({src['repo']} {ref}) @ {sha[:7]}", file=sys.stderr)
        fetched.append((src["name"], src["repo"], sha))
    return fetched


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["fetch", "list"])
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--sources-file", type=Path,
                        help="fetch: also write '<name> <repo> <sha>' lines here")
    args = parser.parse_args()

    content_dir = args.workspace / "content"
    external_dir = args.workspace / "external"
    try:
        if args.command == "fetch":
            fetched = fetch_sources(content_dir, external_dir)
            if args.sources_file:
                args.sources_file.parent.mkdir(parents=True, exist_ok=True)
                args.sources_file.write_text(
                    "".join(f"{n} {r} {s}\n" for n, r, s in fetched), encoding="utf-8")
        else:
            for e in build_plan(content_dir, external_dir):
                print(f"{e['id']}\t{e['dir']}\t{json.dumps(e['meta_defaults'] or {}, ensure_ascii=False)}")
    except DictionaryBuildError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
