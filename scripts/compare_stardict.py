#!/usr/bin/env python3
"""Compares two StarDict dictionary directories by *content*.

Exit status: 0 if equivalent, 1 if different (or the old one is missing).

What is ignored:
  - the 'description=' line of the .ifo (that is where the version lives)
  - compression noise in *.dz files (gzip header timestamp etc.) - these
    are compared after decompression.
"""
import gzip
import sys
from pathlib import Path


def _normalized_content(path: Path) -> bytes:
    if path.suffix == '.dz':
        with gzip.open(path, 'rb') as f:
            return f.read()
    data = path.read_bytes()
    if path.suffix == '.ifo':
        lines = data.decode('utf-8').splitlines()
        data = '\n'.join(l for l in lines if not l.startswith('description=')).encode('utf-8')
    return data


def same_dictionary(old_dir: Path, new_dir: Path) -> bool:
    if not old_dir.is_dir():
        return False
    old_files = sorted(p.name for p in old_dir.iterdir() if p.is_file())
    new_files = sorted(p.name for p in new_dir.iterdir() if p.is_file())
    if old_files != new_files:
        return False
    return all(_normalized_content(old_dir / n) == _normalized_content(new_dir / n)
               for n in new_files)


def main():
    if len(sys.argv) != 3:
        print("Usage: compare_stardict.py <old_dir> <new_dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if same_dictionary(Path(sys.argv[1]), Path(sys.argv[2])) else 1)


if __name__ == '__main__':
    main()
