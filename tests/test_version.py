"""Version single-source: __version__ must match pyproject.toml."""

import tomllib
from pathlib import Path


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    import codingdude

    assert codingdude.__version__ == expected
