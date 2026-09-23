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
bash tools/scripts/build_dictionaries.sh            # or --workspace DIR
# offline / reuse already-fetched external sources:
SKIP_FETCH=1 bash tools/scripts/build_dictionaries.sh

# tests (from this repo's root)
python3 -m unittest discover -s tests -t .
```

Works with macOS's bash 3.2.

## Workspace layout

```
content/meta.yaml          what to build (below)
content/<id>/meta.yaml     one directory per local dictionary
content/<id>/*.txt         input files
stats/<id>.stats           written by the build; commit these
external/                  fetched external sources   (gitignore)
build/                     build output               (gitignore)
  stardict/<id>/           the StarDict files
  changed_dictionaries.txt ids that got a new version this build
  sources.txt              "<source> <repo> <sha>" per fetched source
dictionaries/              previously published copy  (gitignore; see Versioning)
```

### `content/meta.yaml`

```yaml
dictionaries:              # local: content/<id>/
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

A source's **manifest** has the same format as the `dictionaries:` list
above, relative to the manifest's directory, so the source repo decides
what it offers and how it is laid out. Each listed directory becomes the
dictionary `<dirname><suffix>` (e.g. `kavya-repoA-Nick`). If that
directory has its own `meta.yaml` it is used; otherwise `defaults` is
used, and `name` defaults to the id. Sources are always fetched at the
latest commit of `ref`.

### `content/<id>/meta.yaml`

```yaml
name: Sahitya        # required; StarDict bookname (the .ifo file is <name lowercased>.ifo)
type: shloka         # optional default for files without HEADER:type
skip: [च, वा]        # optional; extra shloka exclusions for the whole dictionary
folders: [kavya]     # optional; also read *.txt one level down in these subdirs
```

## Input files

Top of file: optional `#` comment lines, then optional `HEADER:key=value`
lines. Allowed keys: `title` (source shown as `[title]` on each entry),
`type` (`one-liner` | `notes` | `shloka`), `skip` (`;`-separated shloka
exclusions), `lang` (`en` → no `(eng)` suffix on keys), `shlokakey`,
`auto_shloka` (`true`/`false`).

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
| `++ anvaya text` | keys from these words **instead of** the verse; punctuation and `(…)` are ignored; the line stays in the entry |

`HEADER:auto_shloka=false` turns off keys from the verse text entirely
(only `+`/`++` supply keys). `HEADER:shlokakey=BG,2,2` adds a key built
from the verse number, e.g. `॥३-२१॥` → `BG-03-21` (prefix, then a
zero-pad width per level). Exclusions for verse words come from
`scripts/config/exclusions.yaml`, meta.yaml `skip`, and `HEADER:skip`.

## Versioning

The `.ifo` `description` is the version (`YYYYMMDD-HHMM:PST`). A dictionary
only gets a new version if its content differs from the previously
published copy in `PUBLISHED_DIR` (default `<workspace>/dictionaries`).
The comparison ignores the `description` line and the gzip header of
`*.dz` files. An unchanged dictionary reuses the published files exactly.
