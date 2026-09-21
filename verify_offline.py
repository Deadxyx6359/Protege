#!/usr/bin/env python3
"""Static proof that Akira reaches the network only through its one door.

Run this after every `pip install` and before every release. It exits non-zero
and prints every offending path if anything fails.

Five checks:

1. **Source scan.** Every module in the `akira` package plus the entry points
   is parsed and walked for imports of networking modules, and for the dynamic
   import forms (`__import__`, `importlib.import_module`) that a grep would
   miss.

2. **Reachability scan.** Starting from the entry points, the import graph is
   walked transitively through installed third-party packages. A networking
   module found here is a failure; a networking module that exists in an
   installed distribution but is *not reachable* is reported as informational.

3. **One door.** Five modules are exempt, and each only for the modules named
   in `EXEMPT_IMPORTS`: the runtime guard, which imports `socket` to patch it;
   the Qt guard, which imports `PySide6.QtNetwork` to refuse it; the
   chokepoint `akira.core.net.client`, through which Akira fetches pages from
   sites the person has allowed, reaches accounts they connected, and connects
   a browser's tunnels; and two listeners, the sign-in's return
   `akira.core.net.loopback` and the browser's proxy `akira.core.net.proxy`,
   which import `socket` to listen on this computer, and may bind nowhere else,
   never connect and never look a name up. No other module may open the
   guard's door (`netguard.admitting`), so the chokepoint's rules cannot be
   walked around.

4. **The interface's own door, shut.** Qt fetches in C++, over its own sockets,
   out of sight of both the runtime guard and the Python import scan. So the Qt
   modules that reach the network are forbidden like the stdlib ones, every QML
   engine Akira makes must be given `qtguard.shut`, and no QML or JavaScript
   file under `akira/ui/qml` may import a module that brings its own
   connection, such as `QtWebSockets` or `QtWebEngine`.

5. **The browser, held to the proxy.** The browser Akira drives runs in its own
   process, out of every guard here, so what holds it is that it is started
   with everything sent to the proxy (`akira.core.net.proxy`). Only
   `akira.core.net.browser` may import Playwright, and every browser it starts
   must be given `proxy=`. It may not attach to a browser already running,
   start one that listens for others, make requests from Playwright's own
   driver (`.request`, `route.fetch`), which the proxy never sees, or trust any
   certificate.

A few installed packages import a networking module for something other than
the network: Playwright reads addresses with `urllib.parse`, llama.cpp names a
completion with `uuid4`. Each is declared in `THIRD_PARTY_ALLOWED` with its
reason, and every file of the package is read to hold it to that reason
(`ALLOWANCE_LIMITS`): allowed `uuid`, it may not read the network card with
`uuid1` or `getnode`; allowed `socket`, it may not connect or look a name up.

The walk descends into installed packages, which on Windows sit inside the
standard library's own folder (`Lib\\site-packages`). It once stopped there,
taking every package for the standard library, and so checked none of them.

That distinction in check 2 is the whole point of doing this properly rather
than with grep. `llama-cpp-python` ships `llama_cpp/server/app.py`, which
imports FastAPI and opens sockets. Its presence on disk is unavoidable and
harmless. What matters is that no path from `run.py` reaches it. A grep over
site-packages would fail on this every time and quickly be ignored -- an alarm
that always fires teaches you to stop looking at it.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# Modules whose presence anywhere in the reachable graph is a failure, outside
# the exemptions below. Includes both third-party clients and the stdlib
# primitives beneath them, because blocking only `requests` while permitting
# `socket` proves nothing.
FORBIDDEN_ROOTS = frozenset(
    {
        # stdlib networking
        "socket",
        "ssl",
        "http",
        "urllib",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "nntplib",
        "xmlrpc",
        "socketserver",
        "asyncore",
        "asynchat",
        "webbrowser",
        "wsgiref",
        "uuid",  # uuid.getnode() reads the MAC address; not egress, but identifying
        # third-party clients
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "websocket",
        "websockets",
        "grpc",
        "pycurl",
        "boto3",
        "botocore",
        "huggingface_hub",
        "transformers",
        "openai",
        "anthropic",
        # servers
        "fastapi",
        "starlette",
        "uvicorn",
        "flask",
        "werkzeug",
        "tornado",
        "gradio",
        # telemetry
        "sentry_sdk",
        "posthog",
        "mixpanel",
        "segment",
        "opentelemetry",
    }
)

# Qt modules that reach the network by themselves, in C++, where neither the
# runtime guard nor a reading of Python imports would follow them. Named in
# full, because the rest of PySide6 is the interface.
FORBIDDEN_QT = frozenset(
    {
        "PySide6.QtNetwork",
        "PySide6.QtNetworkAuth",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebSockets",
        "PySide6.QtWebView",
        "PySide6.QtHttpServer",
        "PySide6.QtRemoteObjects",
        "PySide6.QtMqtt",
        "PySide6.QtCoap",
        "PySide6.QtLocation",  # downloads map tiles
        "PySide6.QtMultimedia",  # a media source can be a web address
    }
)

# Packages whose modules are named in `from package import Module`, so the
# alias is what has to be checked.
QT_PACKAGES = frozenset({"PySide6"})

# Standard-library packages imported from the same way, `from urllib import
# parse`: the alias names the module, so the alias alone is what is checked.
SUBMODULE_PACKAGES = frozenset({"urllib", "http", "xmlrpc"})

# The same, as QML imports. A QML file importing one of these can connect
# without going through the engine's access manager, which is what is shut.
FORBIDDEN_QML = frozenset(
    {"QtWebEngine", "QtWebSockets", "QtWebView", "QtLocation", "QtMultimedia",
     "QtRemoteObjects", "QtMqtt", "QtCoap"}
)

QML_ROOT = REPO_ROOT / "akira" / "ui" / "qml"
QML_SUFFIXES = (".qml", ".js", ".mjs")
_QML_IMPORT = re.compile(r"^[ \t]*\.?import[ \t]+([A-Za-z_][\w.]*)", re.M)

# Constructing one of these makes an engine that could fetch on its own.
ENGINE_TYPES = frozenset({"QQmlApplicationEngine", "QQmlEngine", "QQuickView", "QQuickWidget"})

GUARD = "akira.security.netguard"
CHOKEPOINT = "akira.core.net.client"
QT_GUARD = "akira.security.qtguard"
LOOPBACK = "akira.core.net.loopback"
PROXY = "akira.core.net.proxy"

#: The modules that listen: for a sign-in's answer, and for a browser's requests.
LISTENERS = frozenset({LOOPBACK, PROXY})

#: Where a listener may listen: this computer, and nothing else.
LOOPBACK_HOST = "127.0.0.1"

#: What the listener must never do: reach out, or look a name up.
OUTWARD = frozenset({"connect", "connect_ex", "create_connection", "getaddrinfo",
                     "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "sendto"})

#: The one module that drives a browser (C3).
BROWSER = "akira.core.net.browser"

#: Third-party packages Akira runs, and the networking modules each may import at
#: module scope, each with why. Every one was read, and `_allowance_findings`
#: holds it to what was found: a package allowed `uuid` never calls `uuid1` or
#: `getnode`, which read the machine's network card, and one allowed `socket`
#: never opens a connection or looks a name up.
THIRD_PARTY_ALLOWED = {
    # Talks to its driver over pipes. It reads addresses (urllib.parse) and
    # names its waits with uuid4. The browser it starts is a process of its own,
    # held by the proxy.
    "playwright": frozenset({"urllib.parse", "uuid"}),
    # Names each completion with uuid4.
    "llama_cpp": frozenset({"uuid"}),
    # Jinja, which llama.cpp renders chat templates with, quotes text for its
    # urlize filter with urllib.parse.
    "jinja2": frozenset({"urllib.parse"}),
}

#: What a package allowed each module must still never call or import, in any
#: file of it that imports that module, its tests aside.
ALLOWANCE_LIMITS = {
    "uuid": frozenset({"uuid1", "getnode"}),
    "socket": frozenset({"create_connection", "create_server", "getaddrinfo", "gethostbyname",
                         "gethostbyname_ex", "gethostbyaddr", "connect", "connect_ex"}),
    "urllib.parse": frozenset(),
}

#: Who alone may import each of them.
THIRD_PARTY_IMPORTERS = {"playwright": BROWSER}

#: Starting a browser: each must be given the proxy.
LAUNCHES = frozenset({"launch", "launch_persistent_context"})

#: What the browser module must never call, and why: each is a way to or from
#: the network that the proxy does not hold.
UNHELD_CALLS = {
    "connect": "attaches to a browser Akira did not start, which no proxy of Akira's holds",
    "connect_over_cdp": "attaches to a browser Akira did not start, which no proxy of Akira's "
                        "holds",
    "launch_server": "starts a browser that listens for others to drive it",
    "fetch": "sends a request from Playwright's own driver, out of the browser and past the "
             "proxy",
}

#: Playwright's own requests (`APIRequestContext`), made by its driver, past the proxy.
UNHELD_ATTRIBUTES = frozenset({"request"})

#: Trusting any certificate: for tests alone, never in the browser module.
UNVERIFIED = "ignore_https_errors"

#: What shuts an engine's own access to the network.
SHUT = "shut"

#: The guard's door. Only the chokepoint may open it.
ADMISSION = "admitting"

# The three modules that may import networking modules, and exactly which.
#
# `akira.security.netguard` imports `socket` to patch it. It must never
# connect: it replaces connect, bind and resolve with functions that raise, and
# lets through only what the chokepoint has checked.
#
# `akira.core.net.client` is the chokepoint (C1), the one path from Akira to
# the network. Every request through it is held to `net.http` for its site,
# https only, never to this machine or its network, capped, and audited. It may
# import the standard-library pieces a client is built from and nothing more:
# no `requests`, no `urllib.request`.
#
# `akira.security.qtguard` imports `PySide6.QtNetwork` for one thing: an
# access manager that refuses every request, which each QML engine is given.
#
# `akira.core.net.loopback` imports `socket` to listen for one sign-in's answer,
# the browser being sent back to this computer by the provider (C5), and
# `akira.core.net.proxy` to listen for the requests of the browser Akira drives
# (C3), each of which it hands to the chokepoint's `tunnel`. Both may bind only
# to 127.0.0.1, and may never connect or look a name up; `_loopback_findings`
# checks both, and the runtime guard refuses any other bind.
#
# This is asserted by test. Every name added here is a hole in the guarantee,
# so adding one must be a deliberate decision.
EXEMPT_IMPORTS = {
    GUARD: frozenset({"socket"}),
    CHOKEPOINT: frozenset({"socket", "ssl", "http.client", "urllib.parse"}),
    QT_GUARD: frozenset({"PySide6.QtNetwork"}),
    LOOPBACK: frozenset({"socket"}),
    PROXY: frozenset({"socket"}),
}
SOURCE_EXEMPT = frozenset(EXEMPT_IMPORTS)

DYNAMIC_IMPORT_CALLS = frozenset({"__import__", "import_module", "load_module", "exec_module"})

# `akira.plugins` loads user-supplied files by path, which is dynamic import
# by definition -- there is no plain-import formulation of "load whatever the
# user dropped in this directory". Exempting it from the dynamic-import check
# does NOT exempt it from the forbidden-module check, and it does not make the
# loaded plugins safe: nothing static can vouch for a file that did not exist
# when this ran. That gap is closed elsewhere, by refusing to load a plugin
# unless it is explicitly enabled and its SHA-256 still matches what was
# approved. The exemption is reported as a note on every run so it stays
# visible rather than becoming invisible precedent.
DYNAMIC_IMPORT_EXEMPT = frozenset({"akira.plugins"})

# `llama_backend` is listed even though startup imports it lazily. It is the
# only module that pulls in `llama_cpp`, whose subtree contains both an unused
# FastAPI server and a HuggingFace downloader -- exactly the dependency most
# worth walking. Omitting it would leave the largest third-party surface in the
# project unscanned while the report still said PASS.
ENTRY_POINTS = (
    "run.py",
    # The Qt interface's launcher. Until it was listed, nothing it imports --
    # agents, tools, the scheduler, the document readers -- had its import
    # graph walked at all: the scan proved the old Tk app offline and said
    # nothing about the one people now run.
    "shell.py",
    "akira/__init__.py",
    "akira/ui/app.py",
    "akira/models/llama_backend.py",
    # The embedding model imports llama_cpp too, and is loaded from inside a
    # function, which the walk would not otherwise follow.
    "akira/models/embedding.py",
    # The browser (C3), the one module that imports Playwright, so that
    # Playwright's own Python is walked however the tools come to import it.
    "akira/core/net/browser.py",
)


@dataclass
class Finding:
    module: str
    path: Path
    line: int
    detail: str
    severity: str = "error"

    def render(self) -> str:
        rel = self.path
        try:
            rel = self.path.relative_to(REPO_ROOT)
        except ValueError:
            pass
        return f"  {self.severity.upper():5s} {rel}:{self.line}  {self.detail}"


@dataclass
class ScanResult:
    errors: list[Finding] = field(default_factory=list)
    notes: list[Finding] = field(default_factory=list)
    modules_scanned: int = 0
    qml_scanned: int = 0
    external_scanned: int = 0


def top_level(module: str) -> str:
    return module.split(".", 1)[0]


def is_forbidden(module: str) -> bool:
    """Whether importing \a module reaches for the network."""
    if top_level(module) in FORBIDDEN_ROOTS:
        return True
    return any(module == qt or module.startswith(qt + ".") for qt in FORBIDDEN_QT)


def _site_packages() -> list[Path]:
    roots: list[Path] = []
    for key in ("purelib", "platlib"):
        raw = sysconfig.get_paths().get(key)
        if raw:
            path = Path(raw)
            if path.is_dir() and path not in roots:
                roots.append(path)
    for raw in sys.path:
        if raw and raw.endswith(("site-packages", "dist-packages")):
            path = Path(raw)
            if path.is_dir() and path not in roots:
                roots.append(path)
    return roots


def _stdlib_root() -> Path | None:
    raw = sysconfig.get_paths().get("stdlib")
    return Path(raw) if raw else None


def _in_stdlib(path: Path, stdlib: Path | None, packages: list[Path]) -> bool:
    """Whether \a path is the standard library's own, rather than an installed package's.

    On Windows `site-packages` sits inside the standard library's folder
    (`Lib\\site-packages`), so being under that folder is not enough: a check
    that stopped there never looked at a single installed package, and passed.
    """
    if stdlib is None or stdlib not in path.parents:
        return False
    return not any(root in path.parents for root in packages)


def _module_file(module: str, search_roots: list[Path]) -> Path | None:
    """Locate a module's source without importing it.

    Importing to find a file would execute the module's top-level code, which
    for a networking package can itself open a connection. The whole check
    would then have caused the thing it is meant to prevent.
    """
    parts = module.split(".")
    for root in search_roots:
        candidate = root.joinpath(*parts).with_suffix(".py")
        if candidate.is_file():
            return candidate
        package_init = root.joinpath(*parts) / "__init__.py"
        if package_init.is_file():
            return package_init
    return None


@dataclass(frozen=True)
class ImportSite:
    """One import statement, and whether it actually runs on import.

    `module_level` is the distinction the whole reachability check turns on. An
    import at module scope executes the moment the module is imported, so it is
    genuinely part of the reachable graph. An import inside a function body
    executes only if that function is called.

    `llama_cpp.llama` is the concrete case: `Llama.from_pretrained` contains
    `from huggingface_hub import hf_hub_download`, which downloads model weights
    over the network. Akira never calls `from_pretrained` -- models load from
    local paths only. Treating that as a hard failure would make this script red
    on every clean install, and a check that is always red is a check nobody
    reads. It is reported as a note naming the enclosing function so the claim
    "we never call it" stays auditable.
    """

    name: str
    line: int
    module_level: bool
    enclosing: str = ""


_SCOPED_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _imports_in(tree: ast.AST) -> list[ImportSite]:
    """Every module name imported by this AST, tagged with its scope.

    Walks with an explicit stack rather than `ast.walk` because `ast.walk`
    flattens the tree and loses exactly the nesting information we need.
    Relative imports are yielded with their leading dots intact for the caller
    to resolve against the importing module's package.
    """
    found: list[ImportSite] = []
    # (node, enclosing function name or "" for module scope)
    stack: list[tuple[ast.AST, str]] = [(tree, "")]
    while stack:
        node, enclosing = stack.pop()
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(ImportSite(alias.name, node.lineno, not enclosing, enclosing))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                name = ("." * node.level) + (node.module or "")
            elif node.module:
                name = node.module
            else:
                continue
            if name in SUBMODULE_PACKAGES:
                # `from urllib import parse` imports urllib.parse, and only that is
                # what is checked, so allowing `urllib.parse` never allows
                # `from urllib import request`.
                found.extend(ImportSite(f"{name}.{alias.name}", node.lineno, not enclosing,
                                        enclosing) for alias in node.names)
                continue
            found.append(ImportSite(name, node.lineno, not enclosing, enclosing))
            if name in QT_PACKAGES:
                # `from PySide6 import QtNetwork` names the module in the alias.
                found.extend(ImportSite(f"{name}.{alias.name}", node.lineno, not enclosing,
                                        enclosing) for alias in node.names)

        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPED_NODES):
                # Class bodies execute on import, so a class is not a new scope
                # for this purpose -- only functions and lambdas are.
                child_scope = getattr(child, "name", "<lambda>")
                stack.append((child, f"{enclosing}.{child_scope}" if enclosing else child_scope))
            else:
                stack.append((child, enclosing))
    return found


def _resolve_relative(name: str, importer: str, is_package: bool) -> str:
    """Turn a leading-dot relative import into an absolute module name."""
    level = len(name) - len(name.lstrip("."))
    remainder = name[level:]
    parts = importer.split(".")
    if not is_package:
        parts = parts[:-1]
    if level > 1:
        parts = parts[: -(level - 1)] if level - 1 <= len(parts) else []
    base = ".".join(parts)
    if remainder:
        return f"{base}.{remainder}" if base else remainder
    return base


def _dynamic_import_findings(tree: ast.AST, module: str, path: Path) -> list[Finding]:
    """Flag dynamic import machinery.

    Any of these can name a module at runtime, which defeats static analysis
    entirely. Akira uses none of them, so their presence is itself the
    finding -- we do not attempt to evaluate the argument.
    """
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ""
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name in DYNAMIC_IMPORT_CALLS:
            findings.append(
                Finding(
                    module=module,
                    path=path,
                    line=node.lineno,
                    detail=(
                        f"dynamic import via {name}() -- defeats static verification; "
                        "use a plain import statement"
                    ),
                )
            )
    return findings


def _exempt_findings(tree: ast.AST, module: str, path: Path) -> list[Finding]:
    """An exempt module imports only the networking modules its exemption names,
    and the guard never connects."""
    findings: list[Finding] = []
    allowed = EXEMPT_IMPORTS.get(module, frozenset())
    for site in _imports_in(tree):
        if site.name.startswith("."):
            continue
        if is_forbidden(site.name) and site.name not in allowed:
            findings.append(Finding(
                module, path, site.line,
                f"imports networking module {site.name!r}, which its exemption does not "
                f"cover (it may import {', '.join(sorted(allowed))})"))
    if module == GUARD:
        # The guard may reference socket but must never connect, except through
        # its saved originals, which is how it lets the chokepoint through.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("connect", "connect_ex", "create_connection"):
                    if not _is_original_dispatch(node):
                        findings.append(Finding(
                            module, path, node.lineno,
                            f"exempt module calls {node.func.attr}() -- the netguard may "
                            "reference socket but must never connect"))
    if module in LISTENERS:
        findings.extend(_loopback_findings(tree, module, path))
    return findings


def _loopback_findings(tree: ast.AST, module: str, path: Path) -> list[Finding]:
    """A listener listens on this computer only, and never reaches out."""
    constants = {node.targets[0].id: node.value.value
                 for node in getattr(tree, "body", [])
                 if isinstance(node, ast.Assign) and len(node.targets) == 1
                 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called(node)
        if name in OUTWARD:
            findings.append(Finding(
                module, path, node.lineno,
                f"calls {name}() -- a listener may only listen on this computer, never reach out"))
        elif name == "bind":
            where = node.args[0] if node.args else None
            host = where.elts[0] if isinstance(where, ast.Tuple) and where.elts else None
            value = (host.value if isinstance(host, ast.Constant)
                     else constants.get(host.id) if isinstance(host, ast.Name) else None)
            if value != LOOPBACK_HOST:
                findings.append(Finding(
                    module, path, node.lineno,
                    f"binds to something other than {LOOPBACK_HOST} -- a listener listens on "
                    "this computer only"))
    return findings


def _browser_findings(tree: ast.AST, module: str, path: Path) -> list[Finding]:
    """Only the browser module drives a browser, and every one it starts uses the proxy."""
    findings: list[Finding] = []
    for site in _imports_in(tree):
        owner = THIRD_PARTY_IMPORTERS.get(top_level(site.name))
        if owner and module != owner:
            findings.append(Finding(
                module, path, site.line,
                f"imports {site.name!r}, which only {owner} may: the browser it drives "
                "must go through the proxy"))
    if module != BROWSER:
        return findings
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in UNHELD_ATTRIBUTES:
            findings.append(Finding(
                module, path, node.lineno,
                f"uses .{node.attr} -- Playwright's own requests come from its driver, out of "
                "the browser and past the proxy"))
        elif ((isinstance(node, ast.keyword) and node.arg == UNVERIFIED)
              or (isinstance(node, ast.Constant) and node.value == UNVERIFIED)):
            findings.append(Finding(
                module, path, node.lineno,
                f"names {UNVERIFIED} -- the browser verifies every site's certificate"))
        if not isinstance(node, ast.Call):
            continue
        name = _called(node)
        if name in UNHELD_CALLS:
            findings.append(Finding(module, path, node.lineno,
                                    f"calls {name}() -- it {UNHELD_CALLS[name]}"))
        elif name in LAUNCHES and not any(k.arg == "proxy" for k in node.keywords):
            findings.append(Finding(
                module, path, node.lineno,
                f"starts a browser with {name}() without proxy= -- every browser Akira starts "
                "sends everything through its proxy"))
    return findings


def _admission_findings(tree: ast.AST, module: str, path: Path) -> list[Finding]:
    """Nothing but the chokepoint opens the guard's door."""
    if module in (GUARD, CHOKEPOINT):
        return []
    findings: list[Finding] = []
    for node in ast.walk(tree):
        opens = (isinstance(node, ast.Attribute) and node.attr == ADMISSION) or (
            isinstance(node, ast.ImportFrom)
            and any(alias.name == ADMISSION for alias in node.names))
        if opens:
            findings.append(Finding(
                module, path, node.lineno,
                f"uses netguard.{ADMISSION}(), which only {CHOKEPOINT} may: every request "
                "must go through the chokepoint and its checks"))
    return findings


def _called(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _engine_findings(tree: ast.AST, module: str, path: Path) -> list[Finding]:
    """A module that makes a QML engine also shuts its own access to the network."""
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    made = [node for node in calls if _called(node) in ENGINE_TYPES]
    if not made or any(_called(node) == SHUT for node in calls):
        return []
    return [Finding(module, path, node.lineno,
                    f"makes a {_called(node)} without {QT_GUARD}.{SHUT}(): the engine could "
                    "fetch web addresses in QML with its own sockets")
            for node in made]


def _qml_findings(text: str, path: Path) -> list[Finding]:
    """No QML or JavaScript file imports a module that brings its own connection."""
    findings: list[Finding] = []
    for match in _QML_IMPORT.finditer(text):
        name = match.group(1)
        if top_level(name) in FORBIDDEN_QML:
            findings.append(Finding(
                _module_name_for(path), path, text.count("\n", 0, match.start()) + 1,
                f"QML imports {name}, which connects without the engine's access manager"))
    return findings


def scan_qml(result: ScanResult) -> None:
    """Check 4, for the interface's own files."""
    if not QML_ROOT.is_dir():
        return
    for path in sorted(QML_ROOT.rglob("*")):
        if path.suffix not in QML_SUFFIXES or not path.is_file():
            continue
        result.qml_scanned += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            result.errors.append(Finding(_module_name_for(path), path, 0, f"cannot read: {exc}"))
            continue
        result.errors.extend(_qml_findings(text, path))


def scan_source(result: ScanResult) -> None:
    """Checks 1, 3 and 4: no networking imports in Akira's own source outside
    the exemptions, no other door opened, and no QML engine left open."""
    sources = sorted((REPO_ROOT / "akira").rglob("*.py"))
    sources += [REPO_ROOT / "run.py", REPO_ROOT / "shell.py"]
    for path in sources:
        if not path.is_file():
            continue
        module = _module_name_for(path)
        result.modules_scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            result.errors.append(Finding(module, path, 0, f"cannot parse: {exc}"))
            continue

        if module in SOURCE_EXEMPT:
            result.errors.extend(_exempt_findings(tree, module, path))
            result.errors.extend(_dynamic_import_findings(tree, module, path))
        else:
            for site in _imports_in(tree):
                if site.name.startswith("."):
                    continue
                if is_forbidden(site.name):
                    # No module-level/function-level distinction here. That
                    # allowance exists for third-party code we did not write and
                    # cannot change. We wrote this code; a lazy import of a
                    # networking module in Akira's own source is a defect
                    # regardless of whether the function is currently called.
                    where = f" inside {site.enclosing}()" if site.enclosing else ""
                    result.errors.append(
                        Finding(module, path, site.line, f"imports networking module {site.name!r}{where}")
                    )
            dynamic = _dynamic_import_findings(tree, module, path)
            if module in DYNAMIC_IMPORT_EXEMPT:
                for finding in dynamic:
                    result.notes.append(
                        Finding(
                            module, path, finding.line,
                            "dynamic import, exempt by design (plugin loader). Plugins are not "
                            "covered by this scan; they load only when explicitly enabled and "
                            "digest-matched.",
                            severity="note",
                        )
                    )
            else:
                result.errors.extend(dynamic)
        result.errors.extend(_admission_findings(tree, module, path))
        result.errors.extend(_engine_findings(tree, module, path))
        result.errors.extend(_browser_findings(tree, module, path))


def _is_original_dispatch(node: ast.Call) -> bool:
    """Allow `_original['connect'](...)` style restoration inside the guard."""
    func = node.func
    return isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id.startswith("_")


def _module_name_for(path: Path) -> str:
    try:
        rel = path.relative_to(REPO_ROOT)
    except ValueError:
        return path.stem
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else path.stem


def scan_reachable(result: ScanResult, max_modules: int = 6000) -> None:
    """Check 2: walk the transitive import graph from the entry points."""
    packages = _site_packages()
    search_roots = [REPO_ROOT] + packages
    stdlib = _stdlib_root()

    queue: list[tuple[str, Path]] = []
    for entry in ENTRY_POINTS:
        path = REPO_ROOT / entry
        if path.is_file():
            queue.append((_module_name_for(path), path))

    seen: set[str] = set()
    while queue and len(seen) < max_modules:
        module, path = queue.pop()
        if module in seen:
            continue
        seen.add(module)

        is_external = not module.startswith("akira") and module != "run"
        if is_external:
            result.external_scanned += 1

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            # An unparseable third-party module cannot be cleared, so say so
            # rather than passing over it in silence.
            if is_external:
                result.notes.append(
                    Finding(module, path, 0, "reachable but unparseable; not verified", severity="note")
                )
            continue

        is_package = path.name == "__init__.py"
        for site in _imports_in(tree):
            resolved = (
                _resolve_relative(site.name, module, is_package) if site.name.startswith(".") else site.name
            )
            if not resolved:
                continue

            if is_forbidden(resolved):
                if resolved in EXEMPT_IMPORTS.get(module, frozenset()):
                    # This module's own exemption. The stdlib is not descended into.
                    continue
                if resolved in THIRD_PARTY_ALLOWED.get(top_level(module), frozenset()):
                    # Declared for the package, with the reason: THIRD_PARTY_ALLOWED.
                    continue
                if site.module_level:
                    result.errors.append(
                        Finding(
                            module,
                            path,
                            site.line,
                            f"reachable module imports networking module {resolved!r} at module scope",
                        )
                    )
                else:
                    result.notes.append(
                        Finding(
                            module,
                            path,
                            site.line,
                            f"lazy import of {resolved!r} inside {site.enclosing}() -- "
                            "only reached if that function is called, and Akira does not call it",
                            severity="note",
                        )
                    )
                continue

            # Only module-level imports extend the reachable set. Following
            # function-local imports would drag in the entire dependency
            # closure of code that never runs, and the resulting graph would
            # describe a program other than this one.
            if not site.module_level:
                continue

            child = _module_file(resolved, search_roots)
            if child is None:
                continue
            # Do not descend into the stdlib beyond the forbidden-root check.
            # It is enormous, largely uninteresting, and its networking modules
            # are already named in FORBIDDEN_ROOTS.
            if _in_stdlib(child, stdlib, packages):
                continue
            if resolved not in seen:
                queue.append((resolved, child))


def _is_test_file(path: Path, base: Path) -> bool:
    parts = path.relative_to(base).parts
    return any(part in ("test", "tests") for part in parts[:-1]) or path.name.startswith("test_")


def _allowance_findings(tree: ast.AST, allowed: frozenset[str], module: str,
                        path: Path) -> list[Finding]:
    """What a file does with a module its package was allowed, past the reason given."""
    imported = {site.name for site in _imports_in(tree)} & allowed
    limits = set().union(*(ALLOWANCE_LIMITS.get(name, frozenset()) for name in imported))
    if not limits:
        return []
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", ""))
            if name in limits:
                findings.append(Finding(module, path, node.lineno,
                                        f"calls {name}(), past what THIRD_PARTY_ALLOWED allows it"))
        elif isinstance(node, ast.ImportFrom) and node.module in imported:
            for alias in node.names:
                if alias.name in limits:
                    findings.append(Finding(module, path, node.lineno,
                                            f"imports {alias.name} from {node.module}, past what "
                                            "THIRD_PARTY_ALLOWED allows it"))
    return findings


def scan_allowances(result: ScanResult) -> None:
    """Hold each package in THIRD_PARTY_ALLOWED to the reason it was allowed.

    Every file of the package is read, reachable or not, since a lazy import can
    reach any of them. Its tests are the exception: Akira never runs them.
    """
    for root in _site_packages():
        for package, allowed in THIRD_PARTY_ALLOWED.items():
            base = root / package
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.py")):
                if _is_test_file(path, base):
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except (OSError, SyntaxError, UnicodeDecodeError):
                    continue
                result.errors.extend(_allowance_findings(tree, allowed, _module_name_for(path),
                                                         path))


def scan_installed_inventory(result: ScanResult) -> None:
    """Informational: networking code that is installed but unreachable.

    Reported as notes, never errors. `llama_cpp/server/` is the expected
    occupant of this list.
    """
    for root in _site_packages():
        for package in ("llama_cpp",):
            base = root / package
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.py")):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except (OSError, SyntaxError, UnicodeDecodeError):
                    continue
                for site in _imports_in(tree):
                    if not site.name.startswith(".") and is_forbidden(site.name):
                        result.notes.append(
                            Finding(
                                _module_name_for(path),
                                path,
                                site.line,
                                f"present on disk but unreachable from Akira: imports {site.name!r}",
                                severity="note",
                            )
                        )
                        break


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quiet", action="store_true", help="suppress informational notes")
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="scan only Akira's own source, skipping the dependency graph walk",
    )
    args = parser.parse_args(argv)

    result = ScanResult()
    scan_source(result)
    scan_qml(result)
    if not args.source_only:
        scan_reachable(result)
        scan_allowances(result)
        scan_installed_inventory(result)

    print(f"verify_offline: scanned {result.modules_scanned} Akira modules, "
          f"{result.qml_scanned} QML and script files, "
          f"{result.external_scanned} reachable external modules")

    if result.notes and not args.quiet:
        print(f"\n{len(result.notes)} informational note(s) -- present but not reachable:")
        for note in result.notes[:20]:
            print(note.render())
        if len(result.notes) > 20:
            print(f"  ... and {len(result.notes) - 20} more")

    if result.errors:
        print(f"\nFAIL: {len(result.errors)} networking finding(s):\n")
        for finding in result.errors:
            print(finding.render())
        print(f"\nAkira must reach the network only through {CHOKEPOINT}. "
              "Fix every finding above.")
        return 1

    print(f"\nPASS: nothing but {CHOKEPOINT} can reach the network, and it only where the "
          "person allowed: sites under net.http, accounts they connected.")
    print(f"What listens ({', '.join(sorted(LISTENERS))}) listens on this computer only.")
    print(f"The browser ({BROWSER}) is started with everything sent through {PROXY}.")
    print(f"The interface's own access to the network is shut ({QT_GUARD}).")
    print("Reminder: this is a static check of Python imports. It cannot see native code "
          "calling the OS directly. An OS firewall rule denying this binary egress is stronger.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
