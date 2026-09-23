"""Shared error type for the dictionary build pipeline.

Every problem with *source data* (as opposed to a genuine bug in this
codebase) should surface as a DictionaryBuildError so that main() can
print a short, actionable message instead of a Python traceback.
"""


class DictionaryBuildError(Exception):
    """A problem with the source dictionary data.

    Carries the file (and, where known, the line number) that caused
    the problem so the message points straight at the fix.
    """

    def __init__(self, message: str, file=None, line: int = None):
        self.message = message
        self.file = str(file) if file is not None else None
        self.line = line

        location = ""
        if self.file:
            location = self.file
            if self.line:
                location += f":{self.line}"
            location += ": "
        super().__init__(f"{location}{message}")

    def with_location(self, file=None, line: int = None) -> "DictionaryBuildError":
        """Return a copy of this error with file/line filled in, unless
        already set. Lets low-level code raise without knowing its
        location, and the caller that *does* know the location annotate
        it on the way up."""
        if self.file is not None and self.line is not None:
            return self
        return DictionaryBuildError(
            self.message,
            file=self.file if self.file is not None else file,
            line=self.line if self.line is not None else line,
        )


class UnmappedCharacterError(DictionaryBuildError):
    """A character had no entry in the itrans transliteration table."""

    def __init__(self, char: str, word: str):
        self.char = char
        self.word = word
        super().__init__(
            f"no transliteration mapping for character {char!r} "
            f"(U+{ord(char):04X}) in word '{word}'"
        )
