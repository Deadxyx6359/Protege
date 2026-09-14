"""QObject adapters between the core layer and QML.

Everything here is a translation: core types in, Qt properties and signals out.
No decisions live at this layer — if a rule is being applied, it belongs in
``akira.core`` where it can be tested without a running Qt application.
"""

from .accounts import AccountsBridge
from .agents import AgentsBridge
from .chat import ChatBridge, MessageListModel
from .coding import CodingBridge
from .documents import DocumentsBridge
from .graph import GraphBridge
from .memory import MemoryBridge
from .monitor import MonitorBridge
from .permissions import ConfirmBridge, PermissionsBridge
from .place import PlaceBridge
from .projects import ProjectsBridge
from .schedule import ScheduleBridge
from .settings import SettingsBridge
from .trace import TraceBridge, TraceListModel

__all__ = [
    "ChatBridge", "MessageListModel", "SettingsBridge",
    "PermissionsBridge", "ConfirmBridge", "ScheduleBridge",
    "TraceBridge", "TraceListModel", "AgentsBridge", "MemoryBridge",
    "ProjectsBridge", "GraphBridge", "MonitorBridge", "PlaceBridge", "AccountsBridge",
    "DocumentsBridge", "CodingBridge",
]
