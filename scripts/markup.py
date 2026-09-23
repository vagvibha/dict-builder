"""Handling for the `**bold**` -> `<b>bold</b>` markup convention.

Applied once per file, on the whole raw file content (headers included --
headers never contain `**`, so this doesn't interact with header parsing).
Validation runs first so a malformed file fails loudly with a line number
rather than silently producing a mis-rendered entry.
"""

from errors import DictionaryBuildError

BOLD_MARKER = "**"
MAX_BOLD_SPAN_LINES = 5

# Tags introduced by this module. Anything that tokenizes free-flowing
# text (currently only the shloka handler) needs to strip these back out
# before splitting on whitespace, so a bolded word doesn't turn into a
# single tag-glued token.
OPEN_TAG = "<b>"
CLOSE_TAG = "</b>"


def strip_bold_tags(text: str) -> str:
    return text.replace(OPEN_TAG, "").replace(CLOSE_TAG, "")


def apply_bold_markup(content: str, filename=None, line_offset: int = 0) -> str:
    """Validates and converts `**...**` pairs in `content` to `<b>...</b>`.

    `content` should already have any HEADER:/# comment lines stripped off
    (those are never subject to bold processing - e.g. a coding-declaration
    comment line like "# --*-- coding: utf-8 --**--" has a stray literal
    "**" that isn't markup). `line_offset` is the number of lines already
    consumed before `content` started, so reported line numbers are
    absolute within the original file.

    Raises DictionaryBuildError if:
      - there's an odd number of `**` markers (one has no partner), or
      - an opening/closing pair is more than MAX_BOLD_SPAN_LINES lines
        apart (almost certainly a missing or mismatched marker rather
        than an intentionally huge bold span).
    """
    positions = []
    idx = 0
    while True:
        idx = content.find(BOLD_MARKER, idx)
        if idx == -1:
            break
        line_no = content.count('\n', 0, idx) + 1 + line_offset
        positions.append((idx, line_no))
        idx += len(BOLD_MARKER)

    if not positions:
        return content

    if len(positions) % 2 != 0:
        _, last_line = positions[-1]
        raise DictionaryBuildError(
            "unmatched '**' marker (no closing '**' found for it)",
            file=filename, line=last_line)

    for (open_off, open_line), (close_off, close_line) in zip(positions[0::2], positions[1::2]):
        if close_line - open_line > MAX_BOLD_SPAN_LINES:
            raise DictionaryBuildError(
                f"'**' opened here has no closing '**' within "
                f"{MAX_BOLD_SPAN_LINES} lines (next '**' is at line {close_line}); "
                "likely a missing or mismatched marker",
                file=filename, line=open_line)

    parts = []
    cursor = 0
    is_open = True
    for offset, _ in positions:
        parts.append(content[cursor:offset])
        parts.append(OPEN_TAG if is_open else CLOSE_TAG)
        is_open = not is_open
        cursor = offset + len(BOLD_MARKER)
    parts.append(content[cursor:])

    return "".join(parts)
