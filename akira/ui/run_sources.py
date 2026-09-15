"""Observe successful read results for presentation, after the real tool gate.

References are evidence of material gathered, not proof the final answer cited
or verified it. All strings are inert UI text. No source is opened from here.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from akira.core.tools import ToolRegistry
from akira.core.net import host_of


def gathered_sources(name, arguments, result, registry):
    if not result.ok or not isinstance(result.data, dict):
        return []
    tool = registry.get(name)
    if tool is None:
        return []
    cleaned = tool.validate(arguments)
    checks = [(r.capability, tool.scope_for(r, cleaned)) for r in tool.requires]
    data = result.data
    candidates = []
    if name in ("fetch_page", "browse_page") and data.get("url"):
        capability = "web.browse" if name == "browse_page" else "net.http"
        checks.append((capability, host_of(str(data["url"]))))
        if name == "browse_page":
            checks.extend((capability, str(site)) for site in data.get("sites", [])[:128])
        candidates.append((data.get("title") or data["url"], data["url"], "Page read", result.content))
    elif name == "web_search":
        for hit in data.get("hits", [])[:16]:
            if isinstance(hit, dict) and hit.get("url"):
                candidates.append((hit.get("title") or hit["url"], hit["url"], "Search result", hit.get("snippet", "")))
    elif name in ("read_file", "read_document") and data.get("path"):
        candidates.append((Path(data["path"]).name, data["path"], "File read", result.content))
    elif name in ("search_notes", "search_documents", "search_conversations"):
        for passage in data.get("passages", [])[:16]:
            if isinstance(passage, dict):
                candidates.append((passage.get("cite") or passage.get("rel") or "Local passage",
                                   passage.get("rel", ""), "Local excerpt", passage.get("text", "")))
    out = []
    for title, locator, kind, body in candidates:
        ident = sha256(f"{name}\n{locator}\n{title}".encode()).hexdigest()[:24]
        text = str(body)
        out.append({"id": ident, "title": str(title)[:240], "locator": str(locator)[:2048],
                    "kind": kind, "tool": name, "body": text[:30000], "checks": checks,
                    "truncated": len(text) > 30000 or bool(data.get("truncated"))})
    return out


class ObservedRegistry:
    """Delegate permission filtering/execution unchanged to the original registry."""
    def __init__(self, registry: ToolRegistry, publish, publish_artifact=None):
        self.registry = registry
        self.publish = publish
        self.publish_artifact = publish_artifact

    def available(self, *args, **kwargs):
        return self.registry.available(*args, **kwargs)

    def invoke(self, name, arguments, context):
        result = self.registry.invoke(name, arguments, context)
        # A display adapter failing must never rerun or change the tool result.
        try:
            for source in gathered_sources(name, arguments, result, self.registry):
                self.publish(source)
            if self.publish_artifact and result.ok and name in ('write_file', 'create_document', 'edit_document', 'update_spreadsheet'):
                cleaned = self.registry.get(name).validate(arguments)
                data = result.data if isinstance(result.data, dict) else {}
                path = data.get('path') if name in ('write_file', 'create_document') else cleaned.get('path')
                if isinstance(path, str) and Path(path).is_absolute():
                    self.publish_artifact({'id': sha256(path.encode()).hexdigest()[:24],
                                           'path': path, 'name': Path(path).name, 'tool': name})
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
        return result
