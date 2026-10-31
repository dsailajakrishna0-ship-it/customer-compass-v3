"""The rules that keep the contract tests a fixed point while the code behind the API changes.

A contract test that reached into internals would have to change with them, and then it proves nothing
about the port. These checks make the boundary mechanical (see tests/README.md)."""

import ast
import re
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
CONTRACT = TESTS / "contract"
README = TESTS / "README.md"
STDLIB = set(sys.stdlib_module_names)
THIRD_PARTY = {"pytest", "pytest_asyncio", "httpx"}
# the app, the database, and the public types a seam may return or raise
ALLOWED_APP_IN_CONFTEST = {
    "app.main",
    "app.db",
    "app.llm.types",
    "app.llm.gateway",
    "app.rag.embeddings",
}


def contract_test_files() -> list[Path]:
    return sorted(p for p in CONTRACT.glob("test_*.py"))


def imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def seam_targets(path: Path) -> set[str]:
    """The string targets of every monkeypatch.setattr("dotted.name", ...) in a file."""
    targets = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setattr"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            targets.add(node.args[0].value)
    return targets


def test_there_are_contract_tests():
    assert len(contract_test_files()) >= 2


@pytest.mark.parametrize("path", contract_test_files(), ids=lambda p: p.name)
def test_a_contract_test_file_imports_only_the_standard_library_and_its_own_fixtures(path):
    offenders = {
        m
        for m in imported_modules(path)
        if m.split(".")[0] not in STDLIB | THIRD_PARTY and not m.startswith("tests.contract")
    }
    assert not offenders, (
        f"{path.name} imports {sorted(offenders)}; contract tests use fixtures, not app code"
    )


@pytest.mark.parametrize("path", contract_test_files(), ids=lambda p: p.name)
def test_a_contract_test_file_patches_nothing_itself(path):
    text = path.read_text()
    assert "setattr" not in text and "mock" not in text.lower() and "patch(" not in text, (
        f"{path.name} patches something; only tests/contract/conftest.py may replace a seam"
    )


def test_conftest_imports_only_the_allowed_parts_of_the_app():
    app_imports = {m for m in imported_modules(CONTRACT / "conftest.py") if m.startswith("app")}
    assert app_imports <= ALLOWED_APP_IN_CONFTEST, sorted(app_imports - ALLOWED_APP_IN_CONFTEST)


def documented_seams() -> set[str]:
    text = README.read_text()
    section = text.split("## The two seams", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `([a-z_.]+)` \|", section, re.MULTILINE))


def test_the_seams_in_conftest_are_exactly_the_documented_ones():
    from tests.contract.conftest import SEAMS

    assert SEAMS == documented_seams()
    assert seam_targets(CONTRACT / "conftest.py") <= SEAMS, (
        "conftest patches something that is not a documented seam"
    )


def test_every_documented_seam_really_exists():
    import importlib

    for seam in documented_seams():
        module, name = seam.rsplit(".", 1)
        assert hasattr(importlib.import_module(module), name), (
            f"{seam} no longer exists: update the seams table"
        )


def test_every_test_file_is_classified_in_the_readme():
    listed = set(
        re.findall(
            r"^\| `([^`]+)` \|", README.read_text().split("## Every test file", 1)[1], re.MULTILINE
        )
    )
    actual = {p.name for p in TESTS.glob("test_*.py")} | {"contract", "agent_internals"}
    assert listed == actual, (
        f"unlisted: {sorted(actual - listed)}; listed but missing: {sorted(listed - actual)}"
    )


def test_the_marker_is_applied_to_the_contract_folder_only():
    """`pytest -m contract` selects exactly the tests under tests/contract (checked by collection)."""
    import subprocess

    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "contract", str(TESTS)],
        capture_output=True,
        text=True,
        cwd=TESTS.parent,
    ).stdout
    collected = [line for line in out.splitlines() if "::" in line]
    assert collected and all(line.startswith("tests/contract/") for line in collected)
