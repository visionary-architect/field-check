"""Field Check — Document corpus health scanner."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("field-check")
except PackageNotFoundError:
    __version__ = "0.1.0"
