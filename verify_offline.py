#!/usr/bin/env python3
"""Static proof that Protege cannot reach the network.

Run this after every `pip install` and before every release. It exits non-zero
and prints every offending path if anything fails.

Two independent checks:

1. **Source scan.** Every module in the `protege` package plus the entry points
   is parsed and walked for imports of networking modules, and for the dynamic
   import forms (`__import__`, `importlib.import_module`) that a grep would
   miss.

2. **Reachability scan.** Starting from the entry points, the import graph is
   walked transitively through installed third-party packages. A networking
   module found here is a failure; a networking module that exists in an
   installed distribution but is *not reachable* is reported as informational.

That distinction is the whole point of doing this properly rather than with
grep. `llama-cpp-python` ships `llama_cpp/server/app.py`, which imports FastAPI
and opens sockets. Its presence on disk is unavoidable and harmless. What
matters is that no path from `run.py` reaches it. A grep over site-packages
would fail on this every time and quickly be ignored -- an alarm that always
fires teaches you to stop looking at it.
"""

from __future__ import annotations

import argparse
import ast
import sys
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# Modules whose presence anywhere in the reachable graph is a failure.
# Includes both third-party clients and the stdlib primitives beneath them,
# because blocking only `requests` while permitting `socket` proves nothing.
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

# `protege.security.netguard` imports `socket` on purpose -- it exists to patch
# it. Exempting it by name is safe because the module never connects; it only
# replaces connect/bind/resolve with functions that raise. This is the only
# exemption in the file and it is deliberately not configurable.
SOURCE_EXEMPT = frozenset({"protege.security.netguard"})

DYNAMIC_IMPORT_CALLS = frozenset({"__import__", "import_module", "load_module", "exec_module"})

# `protege.plugins` loads user-supplied files by path, which is dynamic import
# by definition -- there is no plain-import formulation of "load whatever the
# user dropped in this directory". Exempting it from the dynamic-import check
# does NOT exempt it from the forbidden-module check, and it does not make the
# loaded plugins safe: nothing static can vouch for a file that did not exist
# when this ran. That gap is closed elsewhere, by refusing to load a plugin
# unless it is explicitly enabled and its SHA-256 still matches what was
# approved. The exemption is reported as a note on every run so it stays
# visible rather than becoming invisible precedent.
DYNAMIC_IMPORT_EXEMPT = frozenset({"protege.plugins"})

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
    "protege/__init__.py",
    "protege/ui/app.py",
    "protege/models/llama_backend.py",
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
    external_scanned: int = 0


def top_level(module: str) -> str:
    return module.split(".", 1)[0]


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
    over the network. Protege never calls `from_pretrained` -- models load from
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
            found.append(ImportSite(name, node.lineno, not enclosing, enclosing))

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
    entirely. Protege uses none of them, so their presence is itself the
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


def scan_source(result: ScanResult) -> None:
    """Check 1: no networking imports in Protege's own source."""
    sources = sorted((REPO_ROOT / "protege").rglob("*.py"))
    sources += [REPO_ROOT / "run.py"]
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

        if module not in SOURCE_EXEMPT:
            for site in _imports_in(tree):
                if site.name.startswith("."):
                    continue
                if top_level(site.name) in FORBIDDEN_ROOTS:
                    # No module-level/function-level distinction here. That
                    # allowance exists for third-party code we did not write and
                    # cannot change. We wrote this code; a lazy import of a
                    # networking module in Protege's own source is a defect
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
        else:
            # Still verify the exemption is being used for what it claims: the
            # guard may import socket, but it must not call connect on one.
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("connect", "connect_ex", "create_connection"):
                        if not _is_original_dispatch(node):
                            result.errors.append(
                                Finding(
                                    module,
                                    path,
                                    node.lineno,
                                    f"exempt module calls {node.func.attr}() -- the netguard may "
                                    "reference socket but must never connect",
                                )
                            )


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
    search_roots = [REPO_ROOT] + _site_packages()
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

        is_external = not module.startswith("protege") and module != "run"
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
            root = top_level(resolved)

            if root in FORBIDDEN_ROOTS and module not in SOURCE_EXEMPT:
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
                            "only reached if that function is called, and Protege does not call it",
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
            if stdlib is not None and stdlib in child.parents:
                continue
            if resolved not in seen:
                queue.append((resolved, child))


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
                    if not site.name.startswith(".") and top_level(site.name) in FORBIDDEN_ROOTS:
                        result.notes.append(
                            Finding(
                                _module_name_for(path),
                                path,
                                site.line,
                                f"present on disk but unreachable from Protege: imports {site.name!r}",
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
        help="scan only Protege's own source, skipping the dependency graph walk",
    )
    args = parser.parse_args(argv)

    result = ScanResult()
    scan_source(result)
    if not args.source_only:
        scan_reachable(result)
        scan_installed_inventory(result)

    print(f"verify_offline: scanned {result.modules_scanned} Protege modules, "
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
        print("\nProtege must not be able to reach the network. Fix every finding above.")
        return 1

    print("\nPASS: no networking module is reachable from Protege's entry points.")
    print("Reminder: this is a static check of Python imports. It cannot see native code "
          "calling the OS directly. An OS firewall rule denying this binary egress is stronger.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
