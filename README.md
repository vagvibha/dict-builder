# dict-builder

Turns human-readable Sanskrit/reading notes into StarDict dictionaries.
The code is 100% config driven: it knows nothing about any particular
content. A *content workspace* (usually another repo that includes this
one as a git submodule at `tools/`) supplies the data.

## Quick start

```bash
pip install -r requirements.txt        # pyglossary, pyyaml
# plus dictzip: `brew install dictzip` / `apt-get install dictzip`

# from the content workspace root:
bash tools/scripts/build_dictionaries.sh            # or --workspace DIR, --content-dir DIR
# offline / reuse already-fetched external sources:
SKIP_FETCH=1 bash tools/scripts/build_dictionaries.sh

# tests (from this repo's root)
python3 -m unittest discover -s tests -t .
```

Works with macOS's bash 3.2.

## Workspace layout

```
contents/meta.yaml         what to build (below)
contents/<id>/meta.yaml    one directory per local dictionary
contents/<id>/*.txt        input files (text formats)
contents/<id>/*.csv        input files (table format)
stats/<id>.stats           written by the build; commit these
masters/                   (convention) source data for converters, e.g. TSV exports
external/                  fetched external sources   (gitignore)
build/                     build output               (gitignore)
  generated/<id>/          converter output ('generated:')
  stardict/<id>/           the StarDict files
  changed_dictionaries.txt ids that got a new version this build
  sources.txt              "<source> <repo> <sha>" per fetched source
dictionaries/              previously published copy  (gitignore; see Versioning)
```

The content directory is `contents/` unless `--content-dir` (relative to
the workspace) says otherwise; the rest of this README writes `contents/`.

### `contents/meta.yaml`

```yaml
dictionaries:              # local: contents/<id>/
  - sahitya
sources:                   # optional: dictionaries maintained in other repos
  - name: repoA            # fetched into external/repoA
    repo: https://github.com/<user>/repoA.git
    ref: main              # optional; default = the repo's default branch
    manifest: dict/meta.yaml   # optional; this is the default
    suffix: -repoA-Nick    # optional; default "-<name>"
    dictionaries: [kavya]  # optional; used only if the manifest is missing
    defaults: {type: notes}    # optional; meta for dirs without meta.yaml
```

`generated:` (optional) lists dictionaries produced by a converter on
every build. The converter runs with the workspace root as its current
directory and gets `--output build/generated/<id>/<id>.txt` appended:

```yaml
generated:
  - id: amarakosha
    converter: amarakosha_tsv_to_notes          # scripts/converters/<name>.py
    args: [--words, masters/amarakosha/words.tsv,
           --shlokas, masters/amarakosha/shlokas.tsv,
           --config, masters/amarakosha/amarakosha.yaml]   # --config optional
    meta: {name: Amarakosha}                    # optional; default name=<id>, type=notes
```

A source's **manifest** has the same format as the `dictionaries:` list
above, relative to the manifest's directory, so the source repo decides
what it offers and how it is laid out. Each listed directory becomes the
dictionary `<dirname><suffix>` (e.g. `kavya-repoA-Nick`). If that
directory has its own `meta.yaml` it is used; otherwise `defaults` is
used, and `name` defaults to the id. Sources are always fetched at the
latest commit of `ref`.

`sheets:` (optional) lists Google Sheets tabs that `plan.py sync-sheets`
downloads into the workspace as CSV. The build itself never downloads
them: commit what the sync writes (the content repo's CI does this daily).

```yaml
sheets:
  - path: contents/misc/words.csv     # relative to the workspace; .csv
    url: https://docs.google.com/spreadsheets/d/<id>/edit?gid=123#gid=123
  - path: contents/misc/other.csv
    url: ...
    fetch: false                      # keep the committed file (e.g. while the sheet is being fixed)
```

```bash
# share each spreadsheet (Viewer) with the service account, then:
GOOGLE_APPLICATION_CREDENTIALS=key.json python3 tools/scripts/plan.py sync-sheets
# in CI: GOOGLE_SERVICE_ACCOUNT_JSON=<key file contents> (a repo secret)
```

Tabs are found by gid, so renaming one is fine. Files are tidied for
stable diffs: Unicode NFC, trimmed cells, no empty trailing rows or
columns, LF. Any file under the content directory must also be a valid
table file. It's all or nothing: if any download or check fails, no file
is written.

### `contents/<id>/meta.yaml`

```yaml
name: Sahitya        # required; StarDict bookname (the .ifo file is <name lowercased>.ifo)
type: shloka         # optional default for files without HEADER:type
skip: [च, वा]        # optional; extra shloka exclusions for the whole dictionary
folders: [kavya]     # optional; also read *.txt/*.csv one level down in these subdirs
```

## Input files

Top of file: optional `#` comment lines, then optional `HEADER:key=value`
lines. Allowed keys: `title` (source shown as `[title]` on each entry),
`type` (`one-liner` | `notes` | `shloka`), `skip` (`;`-separated shloka
exclusions), `lang` (`en` → no `(eng)` suffix on keys), `shlokakey`,
`auto_shloka` (`true`/`false`), `show_anvaya` (`true`/`false`).

`**bold**` becomes `<b>bold</b>`. A `**` without a partner, or a pair more
than 5 lines apart, is an error.

**Keys.** Devanagari keys are transliterated to roman (table in
`scripts/config/itrans.yaml`). ASCII keys get an `(eng)` suffix unless
written as `e:KEY`. Pure numbers are dropped.

### one-liner
Each `- ` line is a record; keys go in `((k1;k2))`. The entry text is
everything before the first `((` or `{{`. Without `HEADER:title`, a line
like `[Gita][Bhashya]` sets the source for the lines that follow.

### notes
A record starts with a line `- k1;k2`; every following line, up to the
next line starting with `-`, is the entry.

### shloka
Records are separated by a blank line: the verse, optionally followed by
`====` and notes. By default the keys are the verse's own words, with
punctuation (`, . । ? ॥ ; : ! |`, quotes, `[ ] { }`) treated as a
separator and verse numbers dropped. Special lines in the notes part:

| line | effect |
|---|---|
| `- w1; w2` | don't use these words as keys; `all` = no keys from the verse; `nokey` = no shlokakey |
| `+ k1;k2` | extra keys, used as written |
| `++ anvaya text` | keys from these words **instead of** the verse; punctuation and `(…)` are ignored; the line stays in the entry unless `HEADER:show_anvaya=false` |

`HEADER:auto_shloka=false` turns off keys from the verse text entirely
(only `+`/`++` supply keys). `HEADER:show_anvaya=false` keeps
the `++` keys but leaves the `++` line out of the entry. `HEADER:shlokakey=BG,2,2` adds a key built
from the verse number, e.g. `॥३-२१॥` → `BG-03-21` (prefix, then a
zero-pad width per level). Exclusions for verse words come from
`scripts/config/exclusions.yaml`, meta.yaml `skip`, and `HEADER:skip`.

### table (`.csv`)
Any `.csv` file in a dictionary directory, e.g. a Google Sheets tab, which
can sit next to that dictionary's `.txt` files.

| row | contents |
|---|---|
| 1 | metadata as key/value pairs: `title`, `Dhatu notes`, `keys`, `Words`, `entry`, `Entry` |
| 2 | column headers |
| 3+ | one record per row |

`keys` and `entry` (required) name the column with the lookup keys
(`;`-separated, same key rules as above) and the column with the entry
text. `title` and `lang` work like `HEADER:title` / `HEADER:lang`. Other
columns are ignored, and their order doesn't matter. A row whose keys cell
is empty is skipped. A row with keys but no entry is an error, and so is a
spreadsheet error value (`#N/A`, `#REF!`, …) in either column. Line breaks
in a cell become `<br>`, `**bold**` works, and the keys are shown at the
end of the entry, as in `notes`. Errors give the file line the row starts
on.

## Converters

`scripts/converters/` holds standalone scripts that turn data kept in some
other shape (spreadsheet exports etc.) into one of the input formats above.
Each takes `--output FILE`, exits 2 with a `file:line` message on a data
problem, and can be run by hand or from `generated:`.

**`amarakosha_tsv_to_notes.py`** reads the Amarakosha `words` and `shlokas`
TSV exports and writes one `notes` file: an entry per verse (key
`AK-1-05-001`, its words grouped by meaning, Prev/Next links) and an entry
per word (details, all words of the same meaning, its verse). Columns are
found by header name, set in `converters/config/amarakosha.yaml` (pass your
own copy with `--config`). Every `bword://` link must point at a key in the
output, otherwise it's an error. `--debug --varga 1।05` converts one varga
and turns those errors into warnings, for checking output.

## Versioning

The `.ifo` `description` is the version (`YYYYMMDD-HHMM:PST`). A dictionary
only gets a new version if its content differs from the previously
published copy in `PUBLISHED_DIR` (default `<workspace>/dictionaries`).
The comparison ignores the `description` line and the gzip header of
`*.dz` files. An unchanged dictionary reuses the published files exactly.
