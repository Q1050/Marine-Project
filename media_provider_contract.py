"""Provider-neutral contract for bounded governed identification-media acquisition."""
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class MediaProviderManifest:
    provider: str
    query: dict
    retrieved: int
    end_of_records: bool
    provider_version: str
    records: tuple
    warnings: tuple = ()

class MediaProviderAdapter(Protocol):
    def acquire(self, provider_taxon_id, scientific_name: str, limit: int = 10, page_size: int = 10) -> MediaProviderManifest: ...
    def download(self, url: str) -> tuple[bytes, str]: ...

ELIGIBLE_LICENSE_CLASSES = frozenset({"PUBLIC_DOMAIN", "TRAINING_ALLOWED", "ATTRIBUTION_REQUIRED"})
RESTRICTED_LICENSE_CLASSES = frozenset({"SHARE_ALIKE", "NONCOMMERCIAL_RESTRICTION", "NO_DERIVATIVES", "UNKNOWN", "PROHIBITED", "LICENSE_UNRESOLVED"})
