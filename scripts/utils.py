import argparse
import json
from pathlib import Path

import yaml

from errors import DictionaryBuildError

CONFIG_DIR = Path(__file__).resolve().parent / "config"
EXCLUSIONS_CONFIG_PATH = CONFIG_DIR / "exclusions.yaml"

KNOWN_TYPES = {"one-liner", "notes", "shloka"}


def load_global_exclusions(path: Path = EXCLUSIONS_CONFIG_PATH) -> list:
    """Loads the global (applies-to-every-book) exclusion/stopword list."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    words = data.get("exclusions", [])
    return [str(w) for w in words]


def load_book_meta(dict_dir: Path, defaults: dict = None) -> dict:
    """Loads and validates <dict_dir>/meta.yaml.

    If there is no meta.yaml and `defaults` is given (external dictionaries
    whose source repo doesn't ship one), `defaults` is used in its place.

    Returns a dict with keys: name (str), type (str|None), lang (str|None),
    skip (list[str]), folders (list[str]).
    """
    meta_path = dict_dir / "meta.yaml"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    elif defaults is not None:
        raw = dict(defaults)
    else:
        raise DictionaryBuildError(f"missing meta.yaml in dictionary directory", file=dict_dir)

    if not isinstance(raw, dict) or "name" not in raw or not str(raw["name"]).strip():
        raise DictionaryBuildError("meta.yaml must define a non-empty 'name'", file=meta_path)

    default_type = raw.get("type")
    if default_type is not None and default_type not in KNOWN_TYPES:
        raise DictionaryBuildError(
            f"unknown default type '{default_type}' (expected one of {sorted(KNOWN_TYPES)})",
            file=meta_path)

    return {
        "name": str(raw["name"]).strip(),
        "type": default_type,
        "lang": raw.get("lang"),
        "skip": [str(w) for w in (raw.get("skip") or [])],
        "folders": [str(f) for f in (raw.get("folders") or [])],
    }


def discover_input_files(dict_dir: Path, folders: list) -> list:
    """Top-level *.txt files in dict_dir, plus *.txt files (one level deep,
    non-recursive) in each of the named `folders`. Sorted for determinism."""
    files = sorted(dict_dir.glob("*.txt"))
    for folder in folders:
        sub = dict_dir / folder
        if not sub.is_dir():
            raise DictionaryBuildError(
                f"folders entry '{folder}' in meta.yaml is not a directory",
                file=dict_dir / "meta.yaml")
        files.extend(sorted(sub.glob("*.txt")))
    return files


def parse_arguments():
    """Defines and parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Dictionary content -> tabfile generator (per-book, meta.yaml driven)."
    )

    parser.add_argument(
        "--dict-dir",
        required=True,
        type=Path,
        help="Path to the dictionary's content directory (must contain meta.yaml)"
    )
    parser.add_argument(
        "--file",
        help="Restrict processing to just this one file (path relative to "
             "--dict-dir, or absolute) instead of every file in the book. "
             "Useful for diffing a single file's output against the old pipeline."
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Path where the generated tabfile/babylon output will be written"
    )
    parser.add_argument(
        "--output-format",
        choices=["babylon", "tabfile"],
        default="tabfile"
    )
    parser.add_argument(
        "--stats-file",
        help="Path for the stats file. Defaults to <dict-dir-name>.stats next to --output"
    )
    parser.add_argument(
        "-c", "--count_frequency",
        type=int,
        default=0,
        help="Count word frequency for top-n words if stats enabled"
    )
    parser.add_argument(
        "-s", "--enable_stats",
        action="store_true",
        help="Enable stats tracking"
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="On error, also print the full Python traceback"
    )
    parser.add_argument(
        "--meta-defaults",
        type=json.loads,
        default=None,
        help="JSON object used in place of meta.yaml when the dictionary "
             "directory has none (external sources)"
    )
    parser.add_argument(
        "-v", "--version",
        help="Version string embedded in dict file / stats"
    )

    args = parser.parse_args()

    if not args.dict_dir.exists() or not args.dict_dir.is_dir():
        parser.error(f"--dict-dir does not exist or is not a directory: {args.dict_dir}")

    if not args.stats_file:
        out_path = Path(args.output)
        args.stats_file = str(out_path.parent / f"{args.dict_dir.name}.stats")

    if not args.version:
        args.version = "unspecified"

    return args


def read_header(data: str, allowed_tags: set):
    """Strips leading '#' comment lines and 'HEADER:key=value' lines from
    the top of `data`.

    Returns (headers: dict, remaining_data: str, lines_consumed: int).
    """
    header = dict()
    PREFIX = "HEADER:"
    lines_consumed = 0

    while data.find('#') == 0:
        (line, data) = data.split('\n', 1)
        lines_consumed += 1

    while data.find(PREFIX) == 0:
        (line, data) = data.split('\n', 1)
        lines_consumed += 1
        content = line[len(PREFIX):]
        if '=' not in content:
            raise DictionaryBuildError(f"poorly formed header line: {line!r}", line=lines_consumed)
        k, v = content.split('=', 1)
        if not v.strip():
            raise DictionaryBuildError(f"bad value for header key '{k}'", line=lines_consumed)
        if k in allowed_tags:
            header[k] = v
        else:
            raise DictionaryBuildError(f"unsupported header key '{k}'", line=lines_consumed)

    return (header, data, lines_consumed)


def split_with_line_numbers(text: str, sep: str) -> list:
    """Splits `text` on the literal separator `sep`, returning a list of
    (line_number, chunk) pairs. line_number is the 1-based line (relative
    to the start of `text`) on which the chunk begins. Blank chunks are
    dropped."""
    if not text:
        return []

    results = []
    start = 0
    while True:
        idx = text.find(sep, start)
        line_no = text.count('\n', 0, start) + 1
        if idx == -1:
            chunk = text[start:]
            if chunk.strip():
                results.append((line_no, chunk))
            break
        chunk = text[start:idx]
        if chunk.strip():
            results.append((line_no, chunk))
        start = idx + len(sep)

    return results


def enumerate_nonblank_lines(text: str) -> list:
    """Returns a list of (line_number, line) for every non-blank line in
    `text`, 1-based line numbers relative to the start of `text`."""
    results = []
    for i, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            results.append((i, line.strip()))
    return results


def count_words(word_list):
    """
    Standardized entry and keyword counter.
    Assumes entries in word_list contain a key/index structure.
    """
    total_entries = len(word_list)
    total_index_words = 0

    for entry in word_list:
        indices = getattr(entry, 'indices', []) if not isinstance(entry, dict) else entry.get('indices', [])
        total_index_words += len(indices)

    print("\n--- Processing Run Statistics ---")
    print(f"Total Unique Babylon Cards Generated: {total_entries}")
    print(f"Total Combined Searchable Index Keys: {total_index_words}")
    print("---------------------------------\n")
