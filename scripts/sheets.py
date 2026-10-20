"""Downloads Google Sheets tabs into the workspace ('sheets:' in
<content-dir>/meta.yaml):

    sheets:
      - path: contents/misc/words.csv     # relative to the workspace; must be .csv
        url: https://docs.google.com/spreadsheets/d/<id>/edit?gid=123#gid=123
      - path: contents/misc/other.csv
        url: ...
        fetch: false                      # keep the committed file as it is

The spreadsheets stay private: each one is shared (Viewer) with a Google
service account, and tabs are read through the Sheets API as that account.
The tab is found by its gid, so renaming a tab is fine. Credentials:
  GOOGLE_SERVICE_ACCOUNT_JSON     the key file's contents (GitHub Actions secret)
  GOOGLE_APPLICATION_CREDENTIALS  a path to the key file (handy locally)
Values are read as formatted, i.e. as shown in the sheet.

Every file is tidied the same way, so git only shows real changes:
Unicode NFC, no-break spaces -> spaces, trimmed cells, empty trailing
rows/columns dropped, LF line endings.

All or nothing: a file under the content directory must also parse as a
table dictionary file (table_input.py); if any download or check fails,
nothing is written.

(Same approach and file tidying as vagvibha/kosha's sync_sheets.py.)
"""
import csv
import io
import json
import os
import re
import unicodedata
from pathlib import Path

from errors import DictionaryBuildError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
API = "https://sheets.googleapis.com/v4/spreadsheets"
SHEET_KEYS = {"path", "url", "fetch"}


def parse_url(url: str):
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    g = re.search(r"[#&?]gid=(\d+)", url)
    if not m or not g:
        return None
    return m.group(1), int(g.group(1))


def load_sheets_config(raw: list, workspace: Path, meta_path: Path) -> list:
    """Validates the 'sheets:' list. Returns [{path (Path), rel, url, fetch}]."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DictionaryBuildError("'sheets' must be a list", file=meta_path)
    out, seen = [], set()
    ws = workspace.resolve()
    for i, item in enumerate(raw):
        where = f"sheets[{i}]"
        if not isinstance(item, dict):
            raise DictionaryBuildError(f"{where} must be a mapping", file=meta_path)
        unknown = set(item) - SHEET_KEYS
        if unknown:
            raise DictionaryBuildError(f"{where}: unknown keys {sorted(unknown)}", file=meta_path)
        rel = str(item.get("path") or "").strip()
        if not rel.endswith(".csv"):
            raise DictionaryBuildError(f"{where}: 'path' must be a .csv file", file=meta_path)
        path = (ws / rel).resolve()
        if Path(rel).is_absolute() or ws not in path.parents:
            raise DictionaryBuildError(f"{where}: 'path' must be inside the workspace",
                                       file=meta_path)
        if path in seen:
            raise DictionaryBuildError(f"{where}: path {rel!r} listed twice", file=meta_path)
        seen.add(path)
        url = str(item.get("url") or "").strip()
        if not parse_url(url):
            raise DictionaryBuildError(
                f"{where} ({rel}): 'url' must be a tab URL with the spreadsheet id and "
                "#gid=... (open the tab and copy the address bar)", file=meta_path)
        fetch = item.get("fetch", True)
        if not isinstance(fetch, bool):
            raise DictionaryBuildError(f"{where} ({rel}): 'fetch' must be true or false",
                                       file=meta_path)
        out.append({"path": path, "rel": rel, "url": url, "fetch": fetch})
    return out


def tidy(rows) -> str:
    rows = [[unicodedata.normalize("NFC", str(c).replace(" ", " ")).strip() for c in r]
            for r in rows]
    while rows and not any(rows[-1]):
        rows.pop()
    if rows:
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        while width and not any(r[width - 1] for r in rows):
            width -= 1
        rows = [r[:width] for r in rows]
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


class SheetsClient:
    """Reads tabs through the Sheets API as the service account."""

    def __init__(self):
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import AuthorizedSession
        except ImportError:
            raise DictionaryBuildError("missing libraries: pip install google-auth requests")
        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        try:
            if raw:
                info = json.loads(raw)
            elif key_path:
                info = json.loads(Path(key_path).read_text(encoding="utf-8"))
            else:
                raise DictionaryBuildError(
                    "no credentials: set GOOGLE_SERVICE_ACCOUNT_JSON or "
                    "GOOGLE_APPLICATION_CREDENTIALS")
        except (OSError, ValueError) as e:
            raise DictionaryBuildError(f"can't read the service account key: {e}")
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        self.session = AuthorizedSession(creds)
        self.email = info.get("client_email", "the service account")
        self.titles = {}   # spreadsheet id -> {gid: tab title}

    def _get(self, url, **params):
        r = self.session.get(url, params=params, timeout=120)
        if r.status_code in (403, 404):
            raise DictionaryBuildError(
                f"no access (HTTP {r.status_code}); share the spreadsheet with {self.email} "
                "as Viewer, and check the Sheets API is enabled for the key's project")
        r.raise_for_status()
        return r.json()

    def fetch(self, url: str) -> list:
        sid, gid = parse_url(url)
        if sid not in self.titles:
            meta = self._get(f"{API}/{sid}", fields="sheets.properties(sheetId,title)")
            self.titles[sid] = {t["properties"]["sheetId"]: t["properties"]["title"]
                                for t in meta["sheets"]}
        if gid not in self.titles[sid]:
            raise DictionaryBuildError(
                f"no tab with gid={gid} in that spreadsheet (was it deleted or re-created?)")
        rng = "'" + self.titles[sid][gid].replace("'", "''") + "'"
        data = self._get(f"{API}/{sid}/values/{rng}",
                         valueRenderOption="FORMATTED_VALUE", majorDimension="ROWS")
        return data.get("values", [])


def validate_table(path: Path, text: str) -> int:
    """Parses `text` exactly as a build would read the file. Returns the
    number of entries."""
    import table_input
    import transliteration
    handler = table_input.TableInputHandler(transliteration.Translator(), info=str(path))
    return len(handler.process_file(path, text))


def sync(sheets: list, content_dir: Path, client=None, log=print) -> list:
    """Downloads, tidies and checks every sheet with fetch: true, then
    writes them all, or nothing if anything failed. Returns the paths
    written (changed files only)."""
    todo = [s for s in sheets if s["fetch"]]
    for s in sheets:
        if not s["fetch"]:
            log(f"kept     {s['rel']} (fetch: false)")
    if not todo:
        return []
    client = client or SheetsClient()

    content = content_dir.resolve()
    results, failed = [], []
    for s in todo:
        try:
            text = tidy(client.fetch(s["url"]))
            if not text:
                raise DictionaryBuildError("the tab is empty")
            detail = f"{text.count(chr(10))} lines"
            if content in s["path"].parents:
                detail = f"{validate_table(s['path'], text)} entries"
            results.append((s, text, detail))
        except DictionaryBuildError as e:
            failed.append(f"{s['rel']}: {e}")
        except Exception as e:   # network / API errors
            failed.append(f"{s['rel']}: {type(e).__name__}: {e}")
    if failed:
        raise DictionaryBuildError("sheet sync failed, nothing written:\n  " + "\n  ".join(failed))

    written = []
    for s, text, detail in results:
        p = s["path"]
        old = p.read_text(encoding="utf-8") if p.exists() else None
        if old != text:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            written.append(p)
        log(f"{'updated ' if old != text else 'same    '} {s['rel']} ({detail})")
    return written
