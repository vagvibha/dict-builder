#!/usr/bin/env python3
"""Merges one build's StarDict dictionaries into the published tree.

Several builds (e.g. a daily one and on-demand ones, each its own
--content-dir) publish into one tree:

    dictionaries/<id>/...     every build's dictionaries, side by side
    groups/<group>.txt        the ids each build ("group") owns, one per line

The new tree starts from the published one. This group's dictionaries
from last time (its groups/<group>.txt) are removed, the newly built ones
copied in, and the list rewritten; other groups' dictionaries are left
alone. Without a list yet (first run), only the ids being built are
replaced. An id listed by another group is an error: two builds must not
make the same dictionary.

Usage:
  merge_published.py --published DIR --build build/stardict --group NAME --out DIR

--published may be missing or empty (nothing published yet). Prints
"changed" or "unchanged" (the new tree vs the published one). Exit 2 on
an id conflict.
"""
import argparse
import filecmp
import re
import shutil
import sys
from pathlib import Path

GROUP_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def read_ids(path: Path) -> list:
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def same_tree(a: Path, b: Path) -> bool:
    if not (a.is_dir() and b.is_dir()):
        return False
    cmp = filecmp.dircmp(a, b, ignore=[])
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)
    if mismatch or errors:
        return False
    return all(same_tree(a / d, b / d) for d in cmp.common_dirs)


def merge(published: Path, build: Path, group: str, out: Path) -> bool:
    """Writes the merged tree to `out`; returns True if it differs from
    `published`."""
    if not GROUP_RE.match(group):
        raise ValueError(f"bad group name {group!r}")
    if out.exists():
        shutil.rmtree(out)
    if published.is_dir():
        shutil.copytree(published, out, symlinks=True)
    dicts, groups = out / "dictionaries", out / "groups"
    dicts.mkdir(parents=True, exist_ok=True)
    groups.mkdir(parents=True, exist_ok=True)

    new_ids = sorted(p.name for p in build.iterdir() if p.is_dir()) if build.is_dir() else []
    for other in sorted(groups.glob("*.txt")):
        if other.stem == group:
            continue
        clash = sorted(set(new_ids) & set(read_ids(other)))
        if clash:
            raise ValueError(f"{', '.join(clash)} already published by group "
                             f"'{other.stem}' (groups/{other.name})")

    own = groups / f"{group}.txt"
    old_ids = read_ids(own) if own.exists() else []
    for i in set(old_ids) | set(new_ids):
        shutil.rmtree(dicts / i, ignore_errors=True)
    for i in new_ids:
        shutil.copytree(build / i, dicts / i, symlinks=True)
    if new_ids:
        own.write_text("".join(f"{i}\n" for i in new_ids), encoding="utf-8")
    elif own.exists():
        own.unlink()
    return not same_tree(out, published)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--published", required=True, type=Path)
    p.add_argument("--build", required=True, type=Path)
    p.add_argument("--group", required=True)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args(argv)
    try:
        changed = merge(a.published, a.build, a.group, a.out)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)
    print("changed" if changed else "unchanged")


if __name__ == "__main__":
    main()
