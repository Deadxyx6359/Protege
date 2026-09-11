"""Both launchers put the network guard up first, and the offline proof walks both.

Two gaps found together. The Qt launcher, `shell.py`, never installed the
runtime network guard that `run.py` installs before anything else. And
`verify_offline.py` did not list it as an entry point, so nothing the new
interface imports had its import graph walked — which is how a module that
imports `urllib.request` reached the process without the proof noticing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _order(source: str) -> list[tuple[str, str]]:
    """Top-level Protégé imports and guard installs, in the order they run."""
    order = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("protege"):
            order.append(("import", node.module or ""))
        elif isinstance(node, ast.Import):
            order.extend(("import", alias.name) for alias in node.names
                         if alias.name.startswith("protege"))
        elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
              and ast.unparse(node.value) == "netguard.install()"):
            order.append(("install", ""))
    return order


@pytest.mark.parametrize("launcher", ["run.py", "shell.py"])
def test_the_network_guard_goes_up_before_anything_else(launcher):
    order = _order((ROOT / launcher).read_text(encoding="utf-8"))
    assert ("install", "") in order, f"{launcher} never installs the network guard"
    installed = order.index(("install", ""))
    later = [module for kind, module in order[installed + 1:] if kind == "import"]
    earlier = [module for kind, module in order[:installed]
               if kind == "import" and module != "protege.security"]
    assert later, f"{launcher} imports nothing after the guard"
    assert not earlier, f"{launcher} imports {earlier} before the guard is up"


def test_the_offline_proof_walks_both_launchers():
    source = (ROOT / "verify_offline.py").read_text(encoding="utf-8")
    entry_points = next(
        node.value for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "ENTRY_POINTS" for t in node.targets))
    listed = {element.value for element in entry_points.elts}
    assert {"run.py", "shell.py"} <= listed


def test_the_document_readers_do_not_import_saxutils():
    """`xml.sax.saxutils` imports `urllib.request` at module level."""
    for path in (ROOT / "protege").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("xml.sax"):
                pytest.fail(f"{path.relative_to(ROOT)} imports {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("xml.sax"), path
