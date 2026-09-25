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
from typing import Callable

from PySide6.QtGui import QGuiApplication, QIcon, QWindow

from akira.core.agents import Trace
from akira.core.agents.monitor import Monitor, MonitorService, WatchStore, register_notify_action
from akira.core.brain import embed
from akira.core.brain.distil import PendingStore, register_distil_action, vault_of
from akira.core.brain.index import anywhere, sweep
from akira.core.brain.recall import ContextAssembler
from akira.core.config import AppConfig, autoconfigure, migrate_config, config_dir
from akira.core.connect.inbox import GmailInbox
from akira.core.context.place import PlaceStore
from akira.core.context.weather import Weather, WeatherService
from akira.core.models import ModelRouter, Route
from akira.core.net import browser
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.projects import ProjectStore
from akira.core.review import ensure_review_job, register_review_action
from akira.core.schedule import ActionRegistry, Scheduler, SchedulerService
from akira.core.making.pipeline import DraftStore
from akira.core.schedule.actions import register_agent_actions, register_pipeline_action
from akira.core.tools import default_registry
from akira.design import ThemeController
from akira.ui.bridge import (
    AccountsBridge,
    AgentsBridge,
    ChatBridge,
    CodingBridge,
    ConfirmBridge,
    DocumentsBridge,
    DraftsBridge,
    DrawingBridge,
    GraphBridge,
    MemoryBridge,
    MonitorBridge,
    PermissionsBridge,
    PlaceBridge,
    ProjectsBridge,
    ScheduleBridge,
    SettingsBridge,
    TraceBridge,
    VoiceBridge,
)

from .engine import QML_ROOT, QmlError, build_engine, configure_application, load
from .run_archive import RunArchive

MAIN_QML = QML_ROOT / "Main.qml"
ICON = Path(__file__).parent / "assets" / "akira.ico"


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
    monitor: MonitorBridge | None = None
    place: PlaceBridge | None = None
    accounts: AccountsBridge | None = None
    documents: DocumentsBridge | None = None
    coding: CodingBridge | None = None
    voice: VoiceBridge | None = None
    drawing: DrawingBridge | None = None
    drafts: DraftsBridge | None = None
    scheduler: Scheduler | None = None
    service: SchedulerService | None = None
    monitor_service: MonitorService | None = None
    weather_service: WeatherService | None = None

    housekeeping: Callable[[], None] | None = None
    """Tidying that runs once at start: dropping what expired grants no longer
    cover from the search indexes."""

    def as_context(self) -> dict:
        """The name → object map exposed to QML."""
        exposed = {"Chat": self.chat, "Settings": self.settings}
        for name, obj in (("Permissions", self.permissions), ("Confirm", self.confirm),
                          ("AgentTrace", self.trace), ("Schedule", self.schedule),
                          ("Agents", self.agents), ("Memory", self.memory),
                          ("Projects", self.projects), ("Graph", self.graph),
                          ("Monitor", self.monitor), ("Place", self.place),
                          ("Accounts", self.accounts), ("Documents", self.documents),
                          ("Coding", self.coding), ("Voice", self.voice),
                          ("Drawing", self.drawing), ("Drafts", self.drafts)):
            if obj is not None:
                exposed[name] = obj
        return exposed

    def start_services(self) -> None:
        """Begin background work.

        Only the real application calls this. Previews and tests build the
        very same objects without starting a thread or touching the schedule
        on disk.
        """
        if self.housekeeping is not None:
            self.housekeeping()
        if self.scheduler is not None and self.service is None:
            ensure_review_job(self.scheduler)
            self.service = SchedulerService(self.scheduler)
            self.service.start()
        if self.monitor is not None and self.monitor_service is None:
            self.monitor_service = MonitorService(self.monitor.monitor)
            self.monitor_service.start()
        if self.place is not None and self.place.reader is not None and self.weather_service is None:
            self.weather_service = WeatherService(self.place.reader)
            self.weather_service.start()

    def close(self) -> None:
        self.chat.historySearch.close()
        # The microphone first: nothing is heard once Akira is closing.
        if self.voice is not None:
            self.voice.close()
        if self.drafts is not None:
            self.drafts.close()
        if self.documents is not None:
            self.documents.close()
        if self.coding is not None:
            self.coding.close()
        # A worker blocked waiting for a confirmation would otherwise hold the
        # scheduler thread past shutdown, so it is woken with a refusal first.
        if self.agents is not None:
            self.agents.stop()
        if self.confirm is not None:
            self.confirm.close()
        if self.weather_service is not None:
            self.weather_service.stop()
        # Stop looking for changes before stopping what would act on them.
        if self.monitor_service is not None:
            self.monitor_service.stop()
        if self.service is not None:
            self.service.stop()
        if self.trace is not None:
            self.trace.detach()
        # A page handed to the person lives on a thread of its own. Closing Akira
        # closes its window rather than leaving a browser nobody owns.
        browser.close_handed_over()
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

    documents = DocumentsBridge(policy=working_policy, audit=audit, secrets=secret_store)
    permissions.grantsChanged.connect(documents.invalidate)
    projects.grantsChanged.connect(documents.invalidate)
    projects.currentChanged.connect(documents.invalidate)

    coding = CodingBridge(policy=working_policy, audit=audit, secrets=secret_store)
    permissions.grantsChanged.connect(coding.invalidate)
    projects.grantsChanged.connect(coding.invalidate)
    projects.currentChanged.connect(coding.invalidate)

    # The weather is read in the background, like a scheduled job, so under the
    # global grants: location.read, and net.http for its site.
    place_store = PlaceStore()
    place = PlaceBridge(place_store, Weather(policy=live_policy,
                                             where=lambda: place_store.load().coordinates,
                                             audit=audit))

    # The search indexes hold copies of what the grants allowed. When a grant
    # changes, whatever no grant anywhere still covers is dropped at once, on a
    # worker so a large index does not stall the window.
    def sweep_indexes() -> None:
        covered = anywhere(permissions.policy, *projects.store.policies().values())
        threading.Thread(target=sweep, args=(covered,), name="index-sweep",
                         daemon=True).start()

    permissions.grantsChanged.connect(sweep_indexes)
    projects.grantsChanged.connect(sweep_indexes)

    actions = ActionRegistry()
    scheduler = Scheduler(actions, policy=live_policy, audit=audit,
                          secret_store=secret_store, trace=trace,
                          confirm=confirm.ask)
    schedule = ScheduleBridge(scheduler)
    register_review_action(actions, policy=live_policy, audit=audit,
                           secret_store=secret_store, on_review=schedule.on_review,
                           projects=projects.store.policies)
    register_agent_actions(actions, router=router, registry=default_registry())
    # A pipeline's draft waits for the person, who publishes it under the global
    # grants, as the job that made it ran under them.
    drafts = DraftsBridge(DraftStore(), registry=default_registry(), policy=live_policy,
                          audit=audit, secrets=secret_store)
    register_pipeline_action(actions, router=router, registry=default_registry(),
                             store=drafts.store)
    def model_for(route: str) -> dict:
        resolved = router.resolve(Route.parse(route))
        return {"route": resolved.value, "label": router.status(resolved).label}

    agents = AgentsBridge(router, default_registry(), policy=working_policy,
                          audit=audit, secret_store=secret_store, trace=trace,
                          confirm=confirm.ask,
                          project=lambda: {"id": projects.currentId, "name": projects.currentName},
                          model_for=model_for,
                          archive=RunArchive(config_dir() / "investigations.json" if persist else None))
    permissions.grantsChanged.connect(agents.invalidateSources)
    projects.grantsChanged.connect(agents.invalidateSources)
    projects.currentChanged.connect(agents.invalidateSources)
    pending = PendingStore()
    memory = MemoryBridge(scheduler, policy=live_policy, audit=audit, pending=pending)
    register_distil_action(actions, router=router, pending=pending, projects=projects.store,
                           on_proposed=memory.on_proposed)

    # Connecting a Google address is the person's own act, under the global
    # grants: an account belongs to the person, not to whichever project is open.
    accounts = AccountsBridge(vault=secret_store, policy=live_policy, audit=audit)

    # Watches publish what changed as scheduler events. Like scheduled jobs they
    # run in the background, so they use the global grants; an inbox is read
    # through its connected account.
    monitor = MonitorBridge(Monitor(WatchStore(), policy=live_policy,
                                    publish=scheduler.publish, audit=audit,
                                    inbox=GmailInbox(accounts.google, policy=live_policy,
                                                     audit=audit)),
                            audit=audit)
    monitor.monitor.set_on_change(monitor.changed)
    register_notify_action(actions, notify=monitor.notify)

    # Each chat turn draws on what the person has granted, as agents do, and on
    # the open project. The notes searched are the vault memory is kept in.
    assembler = ContextAssembler(registry=default_registry(), policy=working_policy,
                                 audit=audit, secrets=secret_store, projects=projects.store,
                                 vault=lambda: vault_of(scheduler), place=place.store)

    # The person's own voice, not a project's: listening and speaking answer to
    # the global grants, audio.record and audio.play.
    voice = VoiceBridge(policy=live_policy, audit=audit)
    permissions.grantsChanged.connect(voice.refresh)
    chat = ChatBridge(router, config, context=assembler, project=projects.store.current_id)
    # Replies are read aloud as they stream in, and a call talks to this chat.
    voice.follow(chat)

    return AppContext(
        config=config,
        router=router,
        theme=theme,
        chat=chat,
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
        monitor=monitor,
        place=place,
        accounts=accounts,
        documents=documents,
        coding=coding,
        voice=voice,
        drawing=DrawingBridge(),
        drafts=drafts,
        housekeeping=sweep_indexes,
    )


#: Windows groups taskbar buttons by this, and shows the window's own icon for
#: it. Distinct from the old Tk app's, so the two are not stacked together.
#:
#: Numbered because the shell remembers an icon against the id: an id first seen
#: while the window had no icon of its own keeps the blank one it was given,
#: whatever the window says afterwards. Retiring the id is how that is undone,
#: so raise the number rather than editing the name.
APP_ID = "Akira.Desktop.1"


def _claim_taskbar() -> None:
    """Put the window on the taskbar under its own icon rather than Python's.

    Launched through pythonw, the process is Python as far as Windows can tell,
    and without an explicit id the taskbar shows the interpreter's icon whatever
    the window says. It has to happen before the first window exists.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        # Cosmetic: the app works the same with Python's icon.
        pass


def run_shell(argv: list[str] | None = None) -> int:
    """Start the interface and run until the last window closes."""
    # Before anything reads a setting: the folder may still have its old name.
    moved = migrate_config()
    if moved:
        print(moved, file=sys.stderr)
    _claim_taskbar()
    # Search ranks by meaning as well as words when an embedding model is in
    # models/embed/. Loaded on first use, on the processor.
    embed.use(embed.local())

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

    # The application's icon reaches a window when the window is made, which is
    # here rather than at startup. Set on each window too, so the taskbar and
    # the title bar have it even if the window was built another way.
    if ICON.is_file():
        for root in engine.rootObjects():
            if isinstance(root, QWindow):
                root.setIcon(QIcon(str(ICON)))

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
