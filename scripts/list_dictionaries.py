#!/usr/bin/env python3
"""Prints the dictionaries to build, one per line, from content/meta.yaml."""
import sys
from pathlib import Path

import utils
from errors import DictionaryBuildError


def main():
    if len(sys.argv) != 2:
        print("Usage: list_dictionaries.py <content_dir>", file=sys.stderr)
        sys.exit(2)
    try:
        names = utils.load_dictionary_list(Path(sys.argv[1]))
    except DictionaryBuildError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)
    print('\n'.join(names))


if __name__ == '__main__':
    main()
