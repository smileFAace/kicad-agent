"""kicad-agent: AI-safe structural editing of KiCad files."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kicad-agent")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"
