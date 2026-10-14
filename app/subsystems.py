# -*- coding: utf-8 -*-
"""Subsystem-register med hälsospårning."""

from __future__ import annotations

import logging.handlers
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field
from typing import Any, ClassVar, Dict, List, Optional, Protocol

from app.constants import SubsystemStatus


# ===========================================================================
# SUBSYSTEM PROTOCOLS (Dependency Injection)
# ===========================================================================

class Subsystem(Protocol):
    """Interface för alla subsystems (strukturell typning)."""
    name: ClassVar[str]
    status: SubsystemStatus

    def initialize(self) -> None: ...
    def shutdown(self) -> None: ...
    def health_check(self) -> bool: ...


@dataclass
class SubsystemInfo:
    """Information om ett subsystem (för diagnostics & UI)."""
    name: str
    status: SubsystemStatus
    instance: Optional[Any] = None
    error_count: int = 0
    last_error: Optional[str] = None
    initialized_at: Optional[float] = None
    dependencies: List[str] = field(default_factory=list)
    health_check_count: int = 0
    health_check_failures: int = 0

    @property
    def health_ratio(self) -> float:
        """Returnerar andel lyckade health-checks (0.0–1.0)."""
        if self.health_check_count == 0:
            return 1.0
        return 1.0 - (self.health_check_failures / self.health_check_count)

    @property
    def uptime_sec(self) -> float:
        """Returnerar sekunder sedan init."""
        if self.initialized_at is None:
            return 0.0
        return time.time() - self.initialized_at


class SubsystemRegistry:
    """
    Registry för alla subsystems (dependency injection + health-tracking).
    Trådsäker (RLock).
    """

    def __init__(self) -> None:
        self._subsystems: Dict[str, SubsystemInfo] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._logger = logging.getLogger("Subsystems")

    def register(
        self,
        name: str,
        instance: Any,
        dependencies: Optional[List[str]] = None,
    ) -> None:
        """Registrera en subsystem-instans."""
        with self._lock:
            self._instances[name] = instance
            self._subsystems[name] = SubsystemInfo(
                name=name,
                status=SubsystemStatus.HEALTHY,
                instance=instance,
                initialized_at=time.time(),
                dependencies=dependencies or [],
            )
        self._logger.info(f"Subsystem registrerad: {name!r}")

    def get(self, name: str) -> Optional[Any]:
        """Hämta subsystem-instans (None om ej registrerad)."""
        with self._lock:
            return self._instances.get(name)

    def mark_status(
        self,
        name: str,
        status: SubsystemStatus,
        error: Optional[str] = None,
    ) -> None:
        """Uppdatera subsystem-status + öka error_count om fel."""
        with self._lock:
            if name in self._subsystems:
                self._subsystems[name].status = status
                if error:
                    self._subsystems[name].error_count += 1
                    self._subsystems[name].last_error = error
                    self._subsystems[name].status = SubsystemStatus.DEGRADED
                self._subsystems[name].health_check_count += 1
                if status != SubsystemStatus.HEALTHY:
                    self._subsystems[name].health_check_failures += 1

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Hämta ALLA subsystem-statusar (för diagnostics)."""
        with self._lock:
            return {
                name: {
                    "status": info.status.name,
                    "error_count": info.error_count,
                    "last_error": info.last_error,
                    "initialized_at": info.initialized_at,
                    "uptime_sec": round(info.uptime_sec, 1),
                    "health_ratio": round(info.health_ratio, 3),
                    "dependencies": list(info.dependencies),
                }
                for name, info in self._subsystems.items()
            }

    def shutdown_all(self) -> None:
        """Stäng ALLA subsystems i omvänd ordning (LIFO)."""
        with self._lock:
            names = list(self._subsystems.keys())
        for name in reversed(names):
            with suppress(Exception):
                instance = self._instances.get(name)
                if instance and hasattr(instance, "shutdown"):
                    instance.shutdown()
                    self._logger.info(f"Subsystem nedstängt: {name!r}")
