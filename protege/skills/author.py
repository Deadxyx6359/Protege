"""Authoring skills.

MAIN writes Python to `projects/<project>/skills/`. Two constraints govern what
it may write and when:

* **Only for unlocked topics.** A skill is durable, executable knowledge. If the
  model could author one for a locked topic, it would be writing down what it is
  not supposed to know, in a form that later runs -- a lock bypass with a
  delayed fuse.
* **Skill source goes through the gate like any other output.** Code is text,
  and a leak embedded in a comment or a docstring is still a leak. Blocking here
  costs a regenerated skill; not blocking costs the lock.

Written to disk, never executed. See `sandbox.py` for what happens next, and
for an honest account of how much the subprocess actually protects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..chat import BlockDetail
from ..lock.pipeline import OutputGate
from ..models import ChatMessage, ModelManager, ModelUnavailable, Role
from ..projects import Project, get_project, slugify
from ..schemas import Manifest, SchemaError, Settings, normalize_topic, utcnow_iso
from ..security.paths import PathPolicy, capabilities
from ..store import write_text

MAX_SKILL_CHARS = 20_000

SKILL_SYSTEM = """You write small, self-contained Python programs called skills.

Rules:
- Standard library only. No third-party imports.
- No network access of any kind. No socket, urllib, requests, http, or subprocess.
- No file writes outside the current working directory.
- Print results to stdout. Exit non-zero on failure.
- Include a module docstring saying what the skill does.
- Output only the Python source. No markdown fences, no commentary."""

# Imports refused outright at authoring time. Not a sandbox -- `sandbox.py` is
# candid that a subprocess is not a boundary -- but a skill that plainly reaches
# for the network or the shell should never reach the approval dialog, where a
# tired user might wave it through.
FORBIDDEN_IMPORTS = frozenset(
    {
        "socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib",
        "smtplib", "telnetlib", "xmlrpc", "webbrowser", "subprocess", "multiprocessing",
        "ctypes", "importlib", "shutil", "winreg",
    }
)

IMPORT_RE = re.compile(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import)", re.MULTILINE)
FENCE_RE = re.compile(r"^\s*```(?:python)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


class SkillAuthoringError(RuntimeError):
    """The skill could not be authored."""


@dataclass
class AuthoredSkill:
    """A generated skill awaiting the user's review."""

    topic: str
    name: str
    source: str
    path: Path | None = None
    blocked: bool = False
    block_reason: str = ""
    detail: BlockDetail | None = None
    warnings: list[str] | None = None

    @property
    def filename(self) -> str:
        return f"{slugify(self.name, fallback='skill')}.py"

    @property
    def usable(self) -> bool:
        return not self.blocked and bool(self.source.strip())


def strip_fences(text: str) -> str:
    """Remove a markdown code fence if the model added one despite instructions."""
    match = FENCE_RE.match(text.strip())
    return match.group(1) if match else text.strip()


def scan_imports(source: str) -> tuple[str, ...]:
    """Forbidden top-level modules imported by this source."""
    found: set[str] = set()
    for match in IMPORT_RE.finditer(source):
        module = (match.group(1) or match.group(2) or "").split(".")[0]
        if module in FORBIDDEN_IMPORTS:
            found.add(module)
    return tuple(sorted(found))


def check_syntax(source: str) -> str:
    """Compile the source without running it. Returns an error string or ""."""
    try:
        compile(source, "<skill>", "exec")
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    except ValueError as exc:
        return str(exc)
    return ""


class SkillAuthor:
    def __init__(
        self,
        vault: Path,
        project: str,
        manifest: Manifest,
        settings: Settings,
        manager: ModelManager,
        gate: OutputGate,
    ) -> None:
        self.vault = Path(vault)
        self.project: Project = get_project(self.vault, project)
        self.manifest = manifest
        self.settings = settings
        self.manager = manager
        self.gate = gate

    def author(self, topic: str, description: str) -> AuthoredSkill:
        topic = normalize_topic(topic)

        if not self.manifest.is_unlocked(topic):
            # A skill is durable, executable knowledge. Authoring one for a
            # locked topic writes down what the model is not supposed to know,
            # in a form that later runs.
            raise SkillAuthoringError(
                f"skills can only be authored for unlocked topics; {topic!r} is locked"
            )
        caps = capabilities(self.manifest.trust_tier)
        if not caps.skill_authoring:
            raise SkillAuthoringError(f"skill authoring is not available at {caps.label}")
        if not description.strip():
            raise SkillAuthoringError("describe what the skill should do")

        language = self.settings.skill_language
        if language != "python":
            raise SkillAuthoringError(
                f"skill_language is set to {language!r}; only 'python' is supported"
            )

        try:
            with self.manager.acquire(Role.MAIN) as backend:
                generated = backend.generate(
                    [
                        ChatMessage(role="system", content=SKILL_SYSTEM),
                        ChatMessage(
                            role="user",
                            content=f"Topic: {topic}\n\nWrite a skill that does the following:\n\n{description}",
                        ),
                    ],
                    max_tokens=self.settings.models.max_tokens,
                    temperature=self.settings.models.temperature,
                    top_p=self.settings.models.top_p,
                ).text
        except ModelUnavailable as exc:
            raise SkillAuthoringError(str(exc)) from exc

        source = strip_fences(generated)
        skill = AuthoredSkill(topic=topic, name=description[:60], source=source, warnings=[])

        if not source.strip():
            skill.blocked = True
            skill.block_reason = "the model produced no source"
            return skill
        if len(source) > MAX_SKILL_CHARS:
            skill.blocked = True
            skill.block_reason = f"source is {len(source)} characters, over the {MAX_SKILL_CHARS} limit"
            return skill

        syntax_error = check_syntax(source)
        if syntax_error:
            skill.blocked = True
            skill.block_reason = f"generated source does not parse: {syntax_error}"
            return skill

        forbidden = scan_imports(source)
        if forbidden:
            skill.blocked = True
            skill.block_reason = (
                f"generated source imports {', '.join(forbidden)}, which skills may not use"
            )
            return skill

        # Code is text; a leak in a comment or docstring is still a leak.
        result = self.gate.check(
            f"write a skill about {topic}: {description}", source, allow_decline_shortcut=False
        )
        if not result.allowed:
            skill.blocked = True
            skill.block_reason = f"blocked by the {result.layer} layer: {result.reason}"
            skill.detail = result.to_block_detail()
        return skill

    def save(self, skill: AuthoredSkill, policy: PathPolicy) -> Path:
        """Write an approved-for-saving skill to disk. Does not grant execution."""
        if skill.blocked:
            raise SkillAuthoringError("a blocked skill cannot be saved")
        self.project.skills_dir.mkdir(parents=True, exist_ok=True)
        target = policy.resolve_app(self.project.skills_dir / skill.filename)

        header = (
            f'"""Authored by Protege for topic {skill.topic!r} at {utcnow_iso()}.\n\n'
            "NOT approved for execution. Approval is granted per skill in Settings and is\n"
            "bound to this file's exact contents -- editing it revokes the approval.\n"
            '"""\n\n'
        )
        write_text(target, header + skill.source.rstrip() + "\n")
        skill.path = target
        return target

    def list_skills(self) -> list[Path]:
        if not self.project.skills_dir.is_dir():
            return []
        return sorted(self.project.skills_dir.glob("*.py"))


def validate_skill_topic(topic: str, manifest: Manifest) -> str:
    normalized = normalize_topic(topic)
    if not manifest.is_unlocked(normalized):
        raise SchemaError(f"{normalized!r} is locked; skills can only be authored for unlocked topics")
    return normalized
