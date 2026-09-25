import ast
import warnings

from codingdude.pyparse import parse_python


def test_parse_python_suppresses_syntaxwarning():
    src = 'x = "\\s*JOINT\\s+(\\w+)"'  # invalid escape in non-raw string

    with warnings.catch_warnings():
        warnings.simplefilter('error', SyntaxWarning)
        tree = parse_python(src)  # would raise if the warning leaked

    assert isinstance(tree, ast.Module)


def test_parse_python_still_raises_on_syntax_error():
    import pytest

    with pytest.raises(SyntaxError):
        parse_python('def broken(:')
