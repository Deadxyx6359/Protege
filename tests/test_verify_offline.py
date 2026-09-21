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
        (".schemas", "akira.store", False, "akira.schemas"),
        (".defaults", "akira.personality", True, "akira.personality.defaults"),
        ("..schemas", "akira.lock.manifest", False, "akira.schemas"),
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


# --- the one door ------------------------------------------------------------


def test_the_exemptions_are_the_guards_and_the_chokepoint():
    # Every exemption is a hole in the guarantee. They are listed here with
    # exactly what each may import, so adding one, or widening one, is a
    # deliberate act that changes this test.
    assert vo.EXEMPT_IMPORTS == {
        "akira.security.netguard": frozenset({"socket"}),
        "akira.core.net.client": frozenset({"socket", "ssl", "http.client", "urllib.parse"}),
        "akira.security.qtguard": frozenset({"PySide6.QtNetwork"}),
        "akira.core.net.loopback": frozenset({"socket"}),
        "akira.core.net.proxy": frozenset({"socket"}),
    }
    assert vo.SOURCE_EXEMPT == frozenset(vo.EXEMPT_IMPORTS)


def test_the_sign_ins_return_listens_on_this_computer_only():
    where = vo.REPO_ROOT / "loopback.py"
    listens = _parse('import socket\nHOST = "127.0.0.1"\ns = socket.socket()\n'
                     's.bind((HOST, 0))\ns.listen(1)\ns.accept()\n')
    assert not vo._exempt_findings(listens, vo.LOOPBACK, where)
    anywhere = _parse('import socket\ns = socket.socket()\ns.bind(("0.0.0.0", 0))\n')
    assert "other than 127.0.0.1" in vo._exempt_findings(anywhere, vo.LOOPBACK, where)[0].detail
    reaches = _parse('import socket\ns = socket.socket()\ns.connect(("8.8.8.8", 53))\n')
    assert "never reach out" in vo._exempt_findings(reaches, vo.LOOPBACK, where)[0].detail
    looks_up = _parse('import socket\nsocket.getaddrinfo("example.com", 443)\n')
    assert vo._exempt_findings(looks_up, vo.LOOPBACK, where)
    a_client = _parse("import socket\nimport ssl\n")
    assert vo._exempt_findings(a_client, vo.LOOPBACK, where), "the listener may import only socket"


def test_the_real_listeners_keep_to_it():
    for module, name in ((vo.LOOPBACK, "loopback.py"), (vo.PROXY, "proxy.py")):
        path = vo.REPO_ROOT / "akira" / "core" / "net" / name
        assert not vo._exempt_findings(_parse(path.read_text(encoding="utf-8")), module, path)


def test_only_the_browser_module_may_import_playwright():
    where = vo.REPO_ROOT / "loop.py"
    drives = _parse("from playwright.sync_api import sync_playwright\n")
    [finding] = vo._browser_findings(drives, "akira.core.agents.loop", where)
    assert f"only {vo.BROWSER} may" in finding.detail
    assert not vo._browser_findings(drives, vo.BROWSER, where)


def test_every_browser_akira_starts_goes_through_the_proxy():
    where = vo.REPO_ROOT / "browser.py"
    held = _parse("b = pw.chromium.launch(headless=True, proxy={'server': s})\n")
    assert not vo._browser_findings(held, vo.BROWSER, where)
    loose = _parse("b = pw.chromium.launch(headless=True)\n")
    assert "without proxy=" in vo._browser_findings(loose, vo.BROWSER, where)[0].detail
    kept = _parse("c = pw.chromium.launch_persistent_context('profile')\n")
    assert "without proxy=" in vo._browser_findings(kept, vo.BROWSER, where)[0].detail
    attached = _parse("b = pw.chromium.connect_over_cdp('http://127.0.0.1:9222')\n")
    assert "attaches" in vo._browser_findings(attached, vo.BROWSER, where)[0].detail
    serving = _parse("s = pw.chromium.launch_server(proxy={'server': s})\n")
    assert "listens" in vo._browser_findings(serving, vo.BROWSER, where)[0].detail


@pytest.mark.parametrize("source", [
    "pw.request.new_context().get('https://example.com/')\n",
    "page.request.get('https://example.com/')\n",
    "def handle(route, asked):\n    route.fetch()\n",
])
def test_the_browser_module_makes_no_request_past_the_proxy(source):
    [finding] = vo._browser_findings(_parse(source), vo.BROWSER, vo.REPO_ROOT / "browser.py")
    assert "past the proxy" in finding.detail


@pytest.mark.parametrize("source", [
    "c = b.new_context(ignore_https_errors=True)\n",
    "OPTIONS = {'ignore_https_errors': True}\n",
])
def test_the_browser_module_never_trusts_any_certificate(source):
    [finding] = vo._browser_findings(_parse(source), vo.BROWSER, vo.REPO_ROOT / "browser.py")
    assert "certificate" in finding.detail


def test_each_package_allowed_a_networking_module_is_allowed_only_what_it_was_read_for():
    assert vo.THIRD_PARTY_ALLOWED == {
        "playwright": frozenset({"urllib.parse", "uuid"}),
        "llama_cpp": frozenset({"uuid"}),
        "jinja2": frozenset({"urllib.parse"}),
    }
    assert vo.THIRD_PARTY_IMPORTERS == {"playwright": vo.BROWSER}
    assert set().union(*vo.THIRD_PARTY_ALLOWED.values()) <= set(vo.ALLOWANCE_LIMITS)


# --- installed packages ----------------------------------------------------


def test_installed_packages_are_not_taken_for_the_standard_library(tmp_path):
    # On Windows site-packages is inside the standard library's own folder.
    stdlib = tmp_path / "Lib"
    packages = [stdlib / "site-packages"]
    assert vo._in_stdlib(stdlib / "json" / "__init__.py", stdlib, packages)
    assert not vo._in_stdlib(stdlib / "site-packages" / "jinja2" / "utils.py", stdlib, packages)
    assert not vo._in_stdlib(tmp_path / "elsewhere.py", stdlib, packages)
    assert not vo._in_stdlib(stdlib / "json.py", None, packages)


def test_the_walk_reaches_into_installed_packages_and_finds_nothing():
    result = vo.ScanResult()
    vo.scan_reachable(result)
    assert result.errors == [], "\n".join(f.render() for f in result.errors)
    # llama.cpp, jinja2 and Playwright alone are well over a hundred modules. The
    # walk once stopped at the first of them.
    assert result.external_scanned > 100


def test_a_module_named_in_a_from_import_is_what_is_checked():
    sites = vo._imports_in(_parse("from urllib import parse, request\n"))
    assert [s.name for s in sites] == ["urllib.parse", "urllib.request"]
    # So allowing urllib.parse never lets `from urllib import request` through.
    assert "urllib.request" not in vo.THIRD_PARTY_ALLOWED["jinja2"]


@pytest.mark.parametrize("source", [
    "import uuid\nuuid.uuid1()\n",
    "import uuid\nnode = uuid.getnode()\n",
    "from uuid import getnode\n",
    "import socket\ns = socket.socket()\ns.connect(('example.com', 443))\n",
    "import socket\nsocket.getaddrinfo('example.com', 443)\n",
])
def test_a_package_allowed_a_module_is_held_to_why(source):
    allowed = frozenset({"uuid", "socket"})
    assert vo._allowance_findings(_parse(source), allowed, "pkg.m", vo.REPO_ROOT / "m.py")


@pytest.mark.parametrize("source", [
    "import uuid\nname = uuid.uuid4().hex\n",
    "import socket\npair = socket.socketpair()\n",
    "import sqlite3\ndb = sqlite3.connect(':memory:')\n",  # not the socket's connect
])
def test_what_a_package_was_allowed_for_passes(source):
    allowed = frozenset({"uuid", "socket"})
    assert not vo._allowance_findings(_parse(source), allowed, "pkg.m", vo.REPO_ROOT / "m.py")


def test_a_packages_tests_are_not_held_to_it(tmp_path):
    assert vo._is_test_file(tmp_path / "tests" / "helpers.py", tmp_path)
    assert vo._is_test_file(tmp_path / "test_things.py", tmp_path)
    assert not vo._is_test_file(tmp_path / "backend" / "reduction.py", tmp_path)


def test_the_installed_packages_keep_to_their_allowances():
    result = vo.ScanResult()
    vo.scan_allowances(result)
    assert result.errors == [], "\n".join(f.render() for f in result.errors)


def test_the_browsers_proxy_is_held_to_the_same_rules():
    where = vo.REPO_ROOT / "proxy.py"
    reaches = _parse('import socket\ns = socket.socket()\ns.connect(("8.8.8.8", 443))\n')
    assert "never reach out" in vo._exempt_findings(reaches, vo.PROXY, where)[0].detail
    anywhere = _parse('import socket\ns = socket.socket()\ns.bind(("", 8080))\n')
    assert vo._exempt_findings(anywhere, vo.PROXY, where)


def test_the_chokepoint_may_not_import_a_client_library():
    tree = _parse("import ssl\nimport requests\nfrom urllib.request import urlopen\n")
    findings = vo._exempt_findings(tree, vo.CHOKEPOINT, vo.REPO_ROOT / "fetch.py")
    assert sorted(f.detail.split("'")[1] for f in findings) == ["requests", "urllib.request"]


def test_the_guard_may_not_connect():
    tree = _parse("import socket\nsocket.create_connection(('example.com', 443))\n")
    findings = vo._exempt_findings(tree, vo.GUARD, vo.REPO_ROOT / "netguard.py")
    assert findings and "must never connect" in findings[0].detail


def test_only_the_chokepoint_may_open_the_guard():
    source = ("from akira.security import netguard\n"
              "with netguard.admitting(hosts=('example.com',)):\n    pass\n")
    assert vo._admission_findings(_parse(source), "akira.core.tools.builtin.web",
                                  vo.REPO_ROOT / "web.py")
    assert not vo._admission_findings(_parse(source), vo.CHOKEPOINT, vo.REPO_ROOT / "fetch.py")
    sneaky = "from akira.security.netguard import admitting\n"
    assert vo._admission_findings(_parse(sneaky), "akira.core.agents.loop",
                                  vo.REPO_ROOT / "loop.py")


# --- the interface's own door ----------------------------------------------


@pytest.mark.parametrize("module", ["PySide6.QtNetwork", "PySide6.QtNetwork.QNetworkReply",
                                    "PySide6.QtWebSockets", "PySide6.QtWebEngineCore",
                                    "PySide6.QtNetworkAuth", "PySide6.QtMultimedia"])
def test_qt_modules_that_reach_the_network_are_forbidden(module):
    assert vo.is_forbidden(module)


@pytest.mark.parametrize("module", ["PySide6", "PySide6.QtCore", "PySide6.QtQml",
                                    "PySide6.QtGui", "PySide6.QtQuickControls2"])
def test_the_rest_of_qt_is_the_interface(module):
    assert not vo.is_forbidden(module)


def test_qt_network_named_in_a_from_import_is_seen():
    sites = vo._imports_in(_parse("from PySide6 import QtCore, QtNetwork\n"))
    assert [s.name for s in sites if vo.is_forbidden(s.name)] == ["PySide6.QtNetwork"]


def test_only_the_qt_guard_may_import_qt_network():
    tree = _parse("from PySide6.QtNetwork import QNetworkAccessManager\n")
    assert not vo._exempt_findings(tree, vo.QT_GUARD, vo.REPO_ROOT / "qtguard.py")
    websockets = _parse("from PySide6.QtWebSockets import QWebSocket\n")
    assert vo._exempt_findings(websockets, vo.QT_GUARD, vo.REPO_ROOT / "qtguard.py")


def test_a_qml_engine_must_be_shut():
    made = "from PySide6.QtQml import QQmlApplicationEngine\nengine = QQmlApplicationEngine()\n"
    assert vo._engine_findings(_parse(made), "m", vo.REPO_ROOT / "m.py")
    shut = made + "qtguard.shut(engine)\n"
    assert not vo._engine_findings(_parse(shut), "m", vo.REPO_ROOT / "m.py")


def test_qml_may_not_bring_its_own_connection():
    text = 'import QtQuick\nimport QtWebSockets 1.0\nimport "local.js" as Local\n'
    assert [f.line for f in vo._qml_findings(text, vo.REPO_ROOT / "x.qml")] == [2]
    assert vo._qml_findings(".import QtWebEngine 1.0 as Web\n", vo.REPO_ROOT / "x.js")
    assert not vo._qml_findings(".import QtQuick.LocalStorage 2.0 as Sql\n",
                                vo.REPO_ROOT / "x.js")


# --- end-to-end on the real source tree ------------------------------------


def test_protege_source_has_no_networking_imports_outside_the_door():
    result = vo.ScanResult()
    vo.scan_source(result)
    assert result.errors == [], "\n".join(f.render() for f in result.errors)
    assert result.modules_scanned > 0


def test_protege_qml_brings_no_connection_of_its_own():
    result = vo.ScanResult()
    vo.scan_qml(result)
    assert result.errors == [], "\n".join(f.render() for f in result.errors)
    assert result.qml_scanned > 0


def test_verifier_exits_zero_on_source_only_scan(capsys):
    assert vo.main(["--source-only", "--quiet"]) == 0
    assert "PASS" in capsys.readouterr().out
