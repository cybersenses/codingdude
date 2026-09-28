"""CodingDude — a personal coding agent built with pydantic-ai."""

from importlib.metadata import PackageNotFoundError, version


def _package_version() -> str:
    """Version from installed package metadata (pyproject.toml), '0.0.0' if unreadable."""
    try:
        return version("codingdude")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _package_version()
