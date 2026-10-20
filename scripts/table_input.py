"""The 'table' input format: a .csv file (e.g. a Google Sheets tab).

    row 1   metadata as key, value pairs:  title | Dhatu notes | keys | Words | entry | Entry
    row 2   column headers
    row 3+  one record per row

Metadata keys: 'keys' and 'entry' (required) name the column holding the
lookup keys (';'-separated) and the column holding the entry; 'title'
and 'lang' mean the same as HEADER:title / HEADER:lang. Other columns are
ignored. A row with an empty keys cell is skipped; a row with keys but no
entry is an error, as is any cell showing a spreadsheet error (#N/A,
#REF!, ...) in the keys or entry column.

Entry cells may span lines (quoted CSV); a line break becomes <br>, and
**bold** works as in the text formats. Errors are reported with the
file line on which the row starts.
"""
import csv
import io
import re
from pathlib import Path

import markup
from errors import DictionaryBuildError
from input_handlers import BaseInputHandler

META_KEYS = {"title", "lang", "keys", "entry"}
REQUIRED_META = ("keys", "entry")
# Values Google Sheets shows for a formula error.
SHEET_ERROR_RE = re.compile(r"^#(N/A|REF!|VALUE!|NAME\?|DIV/0!|NUM!|NULL!|ERROR!|SPILL!|CALC!)$")


def _rows_with_lines(f):
    """Yields (first_line_of_row, row) - rows can span lines when quoted."""
    reader = csv.reader(f)
    start = 1
    for row in reader:
        yield start, row
        start = reader.line_num + 1


def parse_meta_row(row: list, path) -> dict:
    cells = [c.strip() for c in row]
    while cells and not cells[-1]:
        cells.pop()
    if len(cells) % 2:
        cells.append("")
    meta = {}
    for i in range(0, len(cells), 2):
        key, value = cells[i], cells[i + 1]
        if not key and not value:
            continue
        if not key:
            raise DictionaryBuildError(
                f"row 1 (metadata): value {value!r} has no key in the cell before it",
                file=path, line=1)
        if key not in META_KEYS:
            raise DictionaryBuildError(
                f"row 1 (metadata): unsupported key {key!r} (expected key/value pairs, "
                f"keys from {sorted(META_KEYS)}; row 1 must be metadata, row 2 the "
                "column headers)", file=path, line=1)
        if key in meta:
            raise DictionaryBuildError(f"row 1 (metadata): {key!r} given twice",
                                       file=path, line=1)
        if not value:
            raise DictionaryBuildError(f"row 1 (metadata): no value for {key!r}",
                                       file=path, line=1)
        meta[key] = value
    missing = [k for k in REQUIRED_META if k not in meta]
    if missing:
        raise DictionaryBuildError(
            f"row 1 (metadata): missing {', '.join(repr(k) for k in missing)} "
            "(the names of the key and entry columns)", file=path, line=1)
    return meta


def read_table(path: Path, text: str = None):
    """Parses a table file (or `text`, with `path` used in messages).
    Returns (headers, records): headers like a text file's HEADER: block
    (title, lang), records [(line, (keys, entry))] in file order, rows with
    an empty keys cell left out."""
    if text is not None:
        f = io.StringIO(text.lstrip("\ufeff"), newline="")
    else:
        try:
            f = open(path, "r", encoding="utf-8-sig", newline="")
        except OSError as e:
            raise DictionaryBuildError(f"cannot read: {e}", file=path)
    with f:
        rows = _rows_with_lines(f)
        first = next(rows, None)
        if first is None:
            raise DictionaryBuildError("empty file (row 1 must be metadata)", file=path, line=1)
        meta = parse_meta_row(first[1], path)

        second = next(rows, None)
        if second is None:
            raise DictionaryBuildError("no column header row (row 2)", file=path, line=2)
        header_line, header = second
        header = [h.strip() for h in header]
        index = {}
        for what in REQUIRED_META:
            name = meta[what]
            if header.count(name) != 1:
                raise DictionaryBuildError(
                    f"{'no' if name not in header else 'more than one'} column {name!r} "
                    f"(for {what!r}) in the header row; columns are {[h for h in header if h]}",
                    file=path, line=header_line)
            index[what] = header.index(name)

        records = []
        for line, row in rows:
            cell = {what: (row[i].strip() if i < len(row) else "") for what, i in index.items()}
            for what, value in cell.items():
                if SHEET_ERROR_RE.match(value):
                    raise DictionaryBuildError(
                        f"{what} cell ({meta[what]!r}) shows a spreadsheet error {value!r}",
                        file=path, line=line)
            keys = [k.strip() for k in cell["keys"].split(";") if k.strip()]
            if not keys:
                continue
            if not cell["entry"]:
                raise DictionaryBuildError(
                    f"no entry ({meta['entry']!r}) for keys {cell['keys']!r}",
                    file=path, line=line)
            entry = markup.apply_bold_markup(cell["entry"].replace("\r", ""),
                                             filename=path, line_offset=line - 1)
            records.append((line, (keys, entry)))

    headers = {k: v for k, v in meta.items() if k in ("title", "lang")}
    return headers, records


class TableInputHandler(BaseInputHandler):
    """Records come from read_table(): (keys, entry). Like notes and
    one-liner, keys are used as given (no exclusions) and shown at the end
    of the entry."""

    def __init__(self, translator=None, exclusion_list=None, info=None):
        super().__init__(translator, exclusion_list=[], info=info)

    def extract_record_parts(self, headers: dict, record) -> tuple:
        keys, entry = record
        return list(keys), entry.replace("\n", "<br>")

    def process_file(self, path: Path, text: str = None) -> list:
        headers, records = read_table(path, text)
        return self.process_records(records, headers)
