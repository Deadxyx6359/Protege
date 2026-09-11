"""Entry point for the Qt shell.

Separate from ``app.py``, which is the Tkinter window being replaced. Both are
runnable for now: the rebuild is a long job, and taking away the working
application on day one would leave nothing to use in the meantime.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QIcon

from protege.core.agents import Trace
from protege.core.brain.distil import PendingStore, register_distil_action, vault_of
from protege.core.brain.recall import ContextAssembler
from protege.core.config import AppConfig, autoconfigure
from protege.core.models import ModelRouter, Route
from protege.core.permissions import AuditLog, Policy, SecretStore
from protege.core.projects import ProjectStore
from protege.core.review import ensure_review_job, register_review_action
from protege.core.schedule import ActionRegistry, Scheduler, SchedulerService
from protege.core.schedule.actions import register_agent_actions
from protege.core.tools import default_registry
from protege.design import ThemeController
from protege.ui.bridge import (
    AgentsBridge,
    ChatBridge,
    ConfirmBridge,
    GraphBridge,
    MemoryBridge,
    PermissionsBridge,
    ProjectsBridge,
    ScheduleBridge,
    SettingsBridge,
    TraceBridge,
)

from .engine import QML_ROOT, QmlError, build_engine, configure_application, load

MAIN_QML = QML_ROOT / "Main.qml"
ICON = Path(__file__).parent / "assets" / "protege.ico"


@dataclass
class AppContext:
    """Everything the QML engine needs, and everything Python must keep alive.

    Context properties do not take ownership. Without a strong reference here,
    the first garbage collection after startup frees an object QML is still
    bound to, and the process dies inside a binding re-evaluation.
    """

    config: AppConfig
    router: ModelRouter
    theme: ThemeController
    chat: ChatBridge
    settings: SettingsBridge
    permissions: PermissionsBridge | None = None
    confirm: ConfirmBridge | None = None
    trace: TraceBridge | None = None
    schedule: ScheduleBridge | None = None
    agents: AgentsBridge | None = None
    memory: MemoryBridge | None = None
    projects: ProjectsBridge | None = None
    graph: GraphBridge | None = None
    scheduler: Scheduler | None = None
    service: SchedulerService | None = None

    def as_context(self) -> dict:
        """The name → object map exposed to QML."""
        exposed = {"Chat": self.chat, "Settings": self.settings}
        for name, obj in (("Permissions", self.permissions), ("Confirm", self.confirm),
                          ("AgentTrace", self.trace), ("Schedule", self.schedule),
                          ("Agents", self.agents), ("Memory", self.memory),
                          ("Projects", self.projects), ("Graph", self.graph)):
            if obj is not None:
                exposed[name] = obj
        return exposed

    def start_services(self) -> None:
        """Begin background work.

        Only the real application calls this. Previews and tests build the
        very same objects without starting a thread or touching the schedule
        on disk.
        """
        if self.scheduler is not None and self.service is None:
            ensure_review_job(self.scheduler)
            self.service = SchedulerService(self.scheduler)
            self.service.start()

    def close(self) -> None:
        # A worker blocked waiting for a confirmation would otherwise hold the
        # scheduler thread past shutdown, so it is woken with a refusal first.
        if self.agents is not None:
            self.agents.stop()
        if self.confirm is not None:
            self.confirm.close()
        if self.service is not None:
            self.service.stop()
        if self.trace is not None:
            self.trace.detach()
        # A turn still streaming holds the model; asking it to stop lets the
        # router unload promptly instead of waiting out the generation.
        if self.chat.busy:
            self.chat.stop()
        # Order matters: save before unloading. A crash during model teardown
        # would otherwise take the last turn with it.
        self.chat.flush()
        # Several gigabytes of model. Leaving it to interpreter shutdown means
        # llama.cpp's destructor races the Python teardown it depends on.
        self.router.close()


def build_context(*, persist: bool = True) -> AppContext:
    """Load configuration and construct the object graph behind the interface.

    Shared with ``tools/preview.py`` so a screenshot exercises the same wiring
    the application does — a view that renders in the preview but not in the
    app is almost always a divergence here.
    """
    config = AppConfig.load()
    if autoconfigure(config) and persist:
        # Persisting immediately means the discovered paths are visible in
        # Settings rather than being silently re-derived on every launch.
        try:
            config.save()
        except OSError as exc:
            print(f"Could not save configuration: {exc}", file=sys.stderr)

    router = ModelRouter(config)
    theme = ThemeController(
        mode=config.appearance,
        reduce_motion=config.reduce_motion,
        on_change=(
            (lambda mode, reduce: _persist_appearance(config, mode, reduce))
            if persist
            else None
        ),
    )
    audit = AuditLog()
    secret_store = SecretStore()
    trace = Trace()
    permissions = PermissionsBridge(Policy.load(), audit)
    confirm = ConfirmBridge()
    projects = ProjectsBridge(ProjectStore(), audit)

    # The scheduler reads the very policy the permission screen edits, so a
    # revocation in Settings reaches the next scheduled run. It is the global
    # policy only: a nightly job must not gain or lose a permission because of
    # which project happened to be open.
    def live_policy() -> Policy:
        return permissions.policy

    # Work started from the interface also gets the open project's own grants.
    def working_policy() -> Policy:
        return projects.effective(permissions.policy)

    actions = ActionRegistry()
    scheduler = Scheduler(actions, policy=live_policy, audit=audit,
                          secret_store=secret_store, trace=trace,
                          confirm=confirm.ask)
    schedule = ScheduleBridge(scheduler)
    register_review_action(actions, policy=live_policy, audit=audit,
                           secret_store=secret_store, on_review=schedule.on_review,
                           projects=projects.store.policies)
    register_agent_actions(actions, router=router, registry=default_registry())
    agents = AgentsBridge(router, default_registry(), policy=working_policy,
                          audit=audit, secret_store=secret_store, trace=trace,
                          confirm=confirm.ask)
    pending = PendingStore()
    memory = MemoryBridge(scheduler, policy=live_policy, audit=audit, pending=pending)
    register_distil_action(actions, router=router, pending=pending,
                           on_proposed=memory.on_proposed)

    # Each chat turn draws on what the person has granted, as agents do, and on
    # the open project. The notes searched are the vault memory is kept in.
    assembler = ContextAssembler(registry=default_registry(), policy=working_policy,
                                 audit=audit, secrets=secret_store, projects=projects.store,
                                 vault=lambda: vault_of(scheduler))

    return AppContext(
        config=config,
        router=router,
        theme=theme,
        chat=ChatBridge(router, config, context=assembler),
        settings=SettingsBridge(config, router),
        permissions=permissions,
        confirm=confirm,
        trace=TraceBridge(trace),
        schedule=schedule,
        scheduler=scheduler,
        agents=agents,
        memory=memory,
        projects=projects,
        graph=GraphBridge(policy=working_policy, audit=audit),
    )


def run_shell(argv: list[str] | None = None) -> int:
    """Start the interface and run until the last window closes."""
    app = QGuiApplication(argv if argv is not None else sys.argv)
    configure_application(app)

    if ICON.is_file():
        app.setWindowIcon(QIcon(str(ICON)))

    ctx = build_context()
    engine, theme = build_engine(theme=ctx.theme, context=ctx.as_context())

    try:
        load(engine, MAIN_QML)
    except QmlError as exc:
        print(exc, file=sys.stderr)
        return 1

    # Without this the process lingers after the window closes, because the
    # engine still holds the root object and Qt has nothing left to quit on.
    engine.quit.connect(app.quit)

    # Scheduled jobs, the daily security review among them, start once the
    # window exists: the first tick may run a review that missed its time.
    ctx.start_services()

    if ctx.config.preload:
        # On a worker thread, and started only after the window exists: loading
        # several gigabytes takes seconds, and doing it before the first frame
        # would turn a fast launch into a hang with nothing on screen.
        threading.Thread(
            target=ctx.router.warm,
            args=(Route.parse(ctx.config.default_route),),
            name="preload",
            daemon=True,
        ).start()

    try:
        return app.exec()
    finally:
        ctx.close()


def _persist_appearance(config: AppConfig, mode: str, reduce_motion: bool) -> None:
    config.appearance = mode
    config.reduce_motion = reduce_motion
    try:
        config.save()
    except OSError:
        # A preference that failed to save is not worth interrupting anyone
        # over; it will simply be the default again next launch.
        pass


if __name__ == "__main__":
    raise SystemExit(run_shell())
