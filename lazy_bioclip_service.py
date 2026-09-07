"""Thread-safe lazy boundary around the existing BioCLIP observation service."""
from __future__ import annotations
import threading

class LazyMarineObservationService:
    def __init__(self, factory=None):
        self._factory = factory
        self._instance = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self):
        return self._instance is not None

    def _get(self):
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    if self._factory is None:
                        from marine_observation_service import MarineObservationService
                        self._factory = MarineObservationService
                    self._instance = self._factory()
        return self._instance

    def analyze(self, *args, **kwargs):
        return self._get().analyze(*args, **kwargs)

    def runtime_identity(self):
        service = self._get()
        return service.runtime_identity() if hasattr(service, "runtime_identity") else {"model_identity": getattr(service, "MODEL_NAME", None)}
