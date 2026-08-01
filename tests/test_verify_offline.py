"""Tests for the offline verifier itself.

A verification script that silently passes is worse than none: it manufactures
confidence. These tests confirm it actually detects what it claims to, using
synthetic modules rather than relying on the real source tree staying clean.
"""

from __future__ import annotations

import ast

import pytest

import verify_offline as vo


def _parse(source: str) -> ast.AST:
    return ast.parse(source)


# --- import scope detection ------------------------------------------------


def test_module_level_import_is_marked_module_level():
    sites = vo._imports_in(_parse("import socket\n"))
    assert [(s.name, s.module_level) for s in sites] == [("socket", True)]


def test_function_local_import_is_not_module_level():
    source = "def fetch():\n    import requests\n    return requests\n"
    sites = vo._imports_in(_parse(source))
    assert len(sites) == 1
    assert sites[0].name == "requests"
    assert not sites[0].module_level
    assert sites[0].enclosing == "fetch"


def test_method_local_import_records_nested_scope():
    source = (
        "class Llama:\n"
        "    def from_pretrained(self):\n"
        "        from huggingface_hub import hf_hub_download\n"
    )
    sites = vo._imports_in(_parse(source))
    assert sites[0].name == "huggingface_hub"
    assert not sites[0].module_level
    assert sites[0].enclosing == "from_pretrained"


def test_class_body_import_counts_as_module_level():
    # A class body executes at import time, so an import there really does run.
    source = "class C:\n    import socket\n"
    sites = vo._imports_in(_parse(source))
    assert sites[0].module_level


def test_conditional_module_level_import_counts_as_module_level():
    # `if TYPE_CHECKING: import x` still sits at module scope. Being
    # conservative here is correct: better to flag an import that may not run
    # than to miss one that does.
    source = "if True:\n    import socket\n"
    sites = vo._imports_in(_parse(source))
    assert sites[0].module_level


def test_relative_imports_are_preserved_with_dots():
    sites = vo._imports_in(_parse("from ..schemas import Manifest\n"))
    assert sites[0].name == "..schemas"


def test_from_import_without_module_is_ignored():
    # `from . import x` has no module name; it must not crash the walker.
    sites = vo._imports_in(_parse("from . import store\n"))
    assert [s.name for s in sites] == ["."]


# --- relative import resolution --------------------------------------------

@pytest.mark.parametrize(
    "name,importer,is_package,expected",
    [
        (".schemas", "protege.store", False, "protege.schemas"),
        (".defaults", "protege.personality", True, "protege.personality.defaults"),
        ("..schemas", "protege.lock.manifest", False, "protege.schemas"),
    ],
)
def test_relative_resolution(name, importer, is_package, expected):
    assert vo._resolve_relative(name, importer, is_package) == expected


# --- dynamic imports -------------------------------------------------------


def test_dynamic_import_is_flagged():
    # Runtime-named imports defeat static analysis entirely, so their presence
    # is itself the finding; we do not try to evaluate the argument.
    source = "import importlib\nm = importlib.import_module('socket')\n"
    findings = vo._dynamic_import_findings(_parse(source), "m", vo.REPO_ROOT / "m.py")
    assert findings and "import_module" in findings[0].detail


def test_builtin_dunder_import_is_flagged():
    findings = vo._dynamic_import_findings(_parse("__import__('socket')\n"), "m", vo.REPO_ROOT / "m.py")
    assert findings


# --- forbidden roots -------------------------------------------------------


@pytest.mark.parametrize(
    "module",
    ["socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp",
     "huggingface_hub", "fastapi", "uvicorn", "sentry_sdk", "webbrowser"],
)
def test_networking_modules_are_forbidden(module):
    assert module in vo.FORBIDDEN_ROOTS


def test_submodules_resolve_to_their_forbidden_root():
    assert vo.top_level("urllib.request") == "urllib"
    assert vo.top_level("urllib.request") in vo.FORBIDDEN_ROOTS


def test_netguard_is_the_only_exemption():
    # Every additional exemption is a hole in the guarantee. Keeping this at
    # exactly one, asserted by test, forces a deliberate decision to add another.
    assert vo.SOURCE_EXEMPT == frozenset({"protege.security.netguard"})


# --- end-to-end on the real source tree ------------------------------------


def test_protege_source_has_no_networking_imports():
    result = vo.ScanResult()
    vo.scan_source(result)
    assert result.errors == [], "\n".join(f.render() for f in result.errors)
    assert result.modules_scanned > 0


def test_verifier_exits_zero_on_source_only_scan(capsys):
    assert vo.main(["--source-only", "--quiet"]) == 0
    assert "PASS" in capsys.readouterr().out
