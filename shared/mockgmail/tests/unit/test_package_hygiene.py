import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2]
SELF_IMPORT = re.compile(r"^\s*(from|import)\s+mockgmail\b", re.MULTILINE)


def _sources() -> list[Path]:
    return sorted(path for path in PACKAGE.rglob("*.py") if "tests" not in path.parts)


def _every_file() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_the_package_never_imports_itself_by_name() -> None:
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in _sources()
        if SELF_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_every_source_file_stays_under_two_hundred_lines() -> None:
    oversized = {
        str(path.relative_to(PACKAGE)): len(path.read_text(encoding="utf-8").splitlines())
        for path in _every_file()
        if len(path.read_text(encoding="utf-8").splitlines()) > 200
    }
    assert oversized == {}


def test_no_source_file_carries_comments_or_docstrings() -> None:
    commented = [
        str(path.relative_to(PACKAGE))
        for path in _sources()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("#")
    ]
    assert commented == []
    documented = [
        str(path.relative_to(PACKAGE))
        for path in _sources()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and ast.get_docstring(node) is not None
    ]
    assert documented == []


def test_the_shell_wrapper_launches_the_client_module() -> None:
    wrapper = (PACKAGE / "bin" / "mockgmail").read_text(encoding="utf-8")
    assert wrapper.startswith("#!/bin/sh\n")
    assert "python3 -u -B -m mockgmail.client" in wrapper
