"""Background task management for kdf."""

import atexit
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kdf_cli.qemu import QemuCommand


class BackgroundTask(ABC):
    """Abstract base class for background tasks."""

    @abstractmethod
    def start(self) -> None:
        """Start the background task."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the background task."""

    @abstractmethod
    def register_with_qemu(self, qemu_cmd: "QemuCommand") -> None:
        """Register this task's QEMU configuration.

        Override this method if the task needs to add QEMU arguments
        or kernel cmdline parameters after starting.

        Args:
            qemu_cmd: QemuCommand instance to configure

        """


class BackgroundTaskManager:
    """Manage all background processes/tasks."""

    def __init__(self) -> None:
        self.tasks = []
        atexit.register(self.cleanup)

    def add_task(self, task: BackgroundTask) -> None:
        """Add a background task to be managed.

        Args:
            task: BackgroundTask instance

        """
        self.tasks.append(task)

    def start_all(self) -> None:
        """Start all registered background tasks."""
        for task in self.tasks:
            task.start()

    def register_all_with_qemu(self, qemu_cmd: "QemuCommand") -> None:
        """Register all tasks with QEMU command.

        Args:
            qemu_cmd: QemuCommand instance to configure

        """
        for task in self.tasks:
            task.register_with_qemu(qemu_cmd)

    def cleanup(self) -> None:
        """Cleanup all background tasks."""
        for task in self.tasks:
            task.stop()
