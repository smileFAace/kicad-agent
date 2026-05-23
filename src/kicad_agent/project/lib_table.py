"""Parse, serialize, and edit sym-lib-table and fp-lib-table files.

KiCad project library tables (sym-lib-table, fp-lib-table) are S-expression
files that list available symbol and footprint libraries. Each entry has a
name, type, URI, options, and description.

Security (threat model):
- T-10-01: Cap entries at 1000 per table (DoS mitigation)
- T-10-03: Validate URI does not contain shell metacharacters
- Path traversal protection via resolve() checks

Usage:
    from kicad_agent.project.lib_table import parse_lib_table, LibEntry

    table = parse_lib_table(Path("sym-lib-table"))
    table.add(LibEntry(name="MyLib", type="KiCad", uri="${KIPRJMOD}/my.kicad_sym"))
    table.to_file(Path("sym-lib-table"))
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import sexpdata

from kicad_agent.serializer.normalizer import normalize_kicad_output

logger = logging.getLogger(__name__)

# Safe identifier pattern (shared with ops/schema.py)
_SAFE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_\-:.#/]+$')

# Shell metacharacter pattern for URI validation (T-10-03)
_SHELL_META_PATTERN = re.compile(r'[`$()]')

# Maximum entries per table (T-10-01)
MAX_ENTRIES = 1000


@dataclass(frozen=True)
class LibEntry:
    """A single library entry in a sym-lib-table or fp-lib-table.

    Attributes:
        name: Library name (e.g. "Device", "power").
        type: Library type (e.g. "KiCad", "Legacy", "GitHub").
        uri: Library URI path, may contain variables like ${KIPRJMOD}.
        options: Library options string (usually empty).
        descr: Library description string.
    """

    name: str
    type: str
    uri: str
    options: str = ""
    descr: str = ""

    def to_sexp(self) -> str:
        """Serialize this entry to S-expression format.

        Returns:
            S-expression string like (lib (name "...")(type "...")(uri "...")...)
        """
        return (
            f'(lib (name "{self.name}")(type "{self.type}")'
            f'(uri "{self.uri}")(options "{self.options}")'
            f'(descr "{self.descr}"))'
        )


@dataclass
class LibTable:
    """A parsed library table (sym-lib-table or fp-lib-table).

    Mutable container for library entries with add/remove/get operations.

    Attributes:
        table_type: "sym_lib_table" or "fp_lib_table".
        entries: Ordered list of library entries.
    """

    table_type: str
    entries: list[LibEntry] = field(default_factory=list)

    def add(self, entry: LibEntry) -> None:
        """Append a library entry. Validates no duplicate name.

        Args:
            entry: The LibEntry to add.

        Raises:
            ValueError: If an entry with the same name already exists,
                        or if the table has reached MAX_ENTRIES (T-10-01).
        """
        if len(self.entries) >= MAX_ENTRIES:
            raise ValueError(
                f"Table has reached maximum entries ({MAX_ENTRIES}). "
                "Cannot add more (T-10-01)."
            )
        for existing in self.entries:
            if existing.name == entry.name:
                raise ValueError(
                    f"Library entry with name '{entry.name}' already exists."
                )
        self.entries.append(entry)

    def remove(self, name: str) -> LibEntry:
        """Remove an entry by name.

        Args:
            name: Library name to remove.

        Returns:
            The removed LibEntry.

        Raises:
            KeyError: If no entry with the given name exists.
        """
        for i, entry in enumerate(self.entries):
            if entry.name == name:
                return self.entries.pop(i)
        raise KeyError(f"Library entry '{name}' not found.")

    def get(self, name: str) -> LibEntry:
        """Look up an entry by name.

        Args:
            name: Library name to look up.

        Returns:
            The matching LibEntry.

        Raises:
            KeyError: If no entry with the given name exists.
        """
        for entry in self.entries:
            if entry.name == name:
                return entry
        raise KeyError(f"Library entry '{name}' not found.")

    def list_entries(self) -> list[LibEntry]:
        """Return all entries.

        Returns:
            Copy of the entries list.
        """
        return list(self.entries)

    def to_sexp(self) -> str:
        """Serialize the table to S-expression format.

        Returns:
            Complete S-expression string for the library table file.
        """
        lines = [f"({self.table_type}"]
        for entry in self.entries:
            lines.append(f"  {entry.to_sexp()}")
        lines.append(")")
        return "\n".join(lines)

    def to_file(self, path: Path) -> None:
        """Write the table to a file with normalization.

        Args:
            path: File path to write.
        """
        content = self.to_sexp()
        normalized = normalize_kicad_output(content)
        path.write_text(normalized, encoding="utf-8")


def _validate_entry_name(name: str) -> None:
    """Validate that a library entry name is safe.

    Args:
        name: Entry name to validate.

    Raises:
        ValueError: If the name contains unsafe characters.
    """
    if not _SAFE_ID_PATTERN.match(name):
        raise ValueError(
            f"Library name '{name}' contains unsafe characters. "
            "Allowed: alphanumeric, underscore, dash, colon, dot, hash, forward slash."
        )


def _validate_uri(uri: str) -> None:
    """Validate that a URI does not contain shell metacharacters (T-10-03).

    Allows ${} variable references (like ${KIPRJMOD}) but blocks
    backticks, command substitution, and other injection vectors.

    Args:
        uri: URI string to validate.

    Raises:
        ValueError: If the URI contains shell metacharacters.
    """
    # Block backticks and command substitution $()
    if "`" in uri:
        raise ValueError(f"URI contains backtick: '{uri}'")
    # Check for $() command substitution (but allow ${} variable references)
    if re.search(r'\$\(', uri):
        raise ValueError(f"URI contains command substitution: '{uri}'")


def _validate_path(path: Path) -> None:
    """Validate path has no traversal (security check).

    Args:
        path: File path to validate.

    Raises:
        ValueError: If path contains traversal sequences.
    """
    resolved = path.resolve()
    parts = resolved.parts
    if ".." in str(path.parts):
        raise ValueError("Path must not contain '..' traversal")


def parse_lib_table(path: Path) -> LibTable:
    """Parse a sym-lib-table or fp-lib-table file.

    Args:
        path: Path to the library table file.

    Returns:
        Parsed LibTable with entries.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file content is malformed.
    """
    _validate_path(path)
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {path}")

    content = resolved.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError("Empty library table file")

    parsed = sexpdata.loads(content)

    # Extract table type from first element
    if not isinstance(parsed, list) or len(parsed) == 0:
        raise ValueError("Malformed library table: expected S-expression list")

    table_type_raw = parsed[0]
    if isinstance(table_type_raw, sexpdata.Symbol):
        table_type = str(table_type_raw)
    else:
        table_type = str(table_type_raw)

    if table_type not in ("sym_lib_table", "fp_lib_table"):
        raise ValueError(
            f"Expected sym_lib_table or fp_lib_table, got '{table_type}'"
        )

    entries: list[LibEntry] = []
    for item in parsed[1:]:
        if not isinstance(item, list):
            continue
        if len(item) == 0:
            continue
        first = item[0]
        if isinstance(first, sexpdata.Symbol) and str(first) == "lib":
            entry = _parse_lib_entry(item)
            entries.append(entry)

    return LibTable(table_type=table_type, entries=entries)


def _parse_lib_entry(sexp: list) -> LibEntry:
    """Parse a single (lib ...) S-expression into a LibEntry.

    Args:
        sexp: Parsed S-expression list for the lib entry.

    Returns:
        LibEntry with extracted fields.
    """
    name = ""
    lib_type = ""
    uri = ""
    options = ""
    descr = ""

    for child in sexp[1:]:
        if not isinstance(child, list) or len(child) < 2:
            continue
        key = child[0]
        if isinstance(key, sexpdata.Symbol):
            key_str = str(key)
            value = child[1]
            if isinstance(value, sexpdata.Symbol):
                value = str(value)
            # value might be a string or a symbol
            value_str = str(value)

            if key_str == "name":
                name = value_str
            elif key_str == "type":
                lib_type = value_str
            elif key_str == "uri":
                uri = value_str
            elif key_str == "options":
                options = value_str
            elif key_str == "descr":
                descr = value_str

    return LibEntry(name=name, type=lib_type, uri=uri, options=options, descr=descr)


def serialize_lib_table(table: LibTable, path: Path) -> None:
    """Serialize a LibTable to a file.

    Generates the S-expression string, normalizes it, and writes to disk.

    Args:
        table: The LibTable to serialize.
        path: File path to write.
    """
    table.to_file(path)
