"""Multi-agent subsystem — task decomposition, parallel workers, message bus.
DNA: Devin (autonomous loop) + Astra (hyper-agentic) + CrewAI (roles).
"""

from .orchestrator import Orchestrator, SubTask, TaskResult
from .worker import Worker, WorkerPool, WorkerConfig
from .bus import MessageBus, Message, SharedContext

__all__ = [
    "Orchestrator", "SubTask", "TaskResult",
    "Worker", "WorkerPool", "WorkerConfig",
    "MessageBus", "Message", "SharedContext",
]