"""Shared pytest configuration.

Ensures the heavy BioCLIP service stack is stubbed consistently so
test modules that import api.py do not attempt to load the model.
This also exposes the SCIENTIFIC_NAMES constant to any test module
that may need to resolve BioCLIP reference labels.
"""

import sys
import types


_SCIENTIFIC_NAMES = {
    "acanthurus_bahianus": "Acanthurus bahianus",
    "acanthurus_coeruleus": "Acanthurus coeruleus",
    "diodon_hystrix": "Diodon hystrix",
    "gymnothorax_funebris": "Gymnothorax funebris",
    "holacanthus_ciliaris": "Holacanthus ciliaris",
    "lactophrys_triqueter": "Lactophrys triqueter",
    "pomacanthus_paru": "Pomacanthus paru",
    "pterois_volitans": "Pterois volitans",
    "sparisoma_viride": "Sparisoma viride",
    "sphyraena_barracuda": "Sphyraena barracuda",
}


def _ensure_stub():
    """Ensure sys.modules['marine_observation_service'] exposes the
    constants any consumer may need (e.g. bioclip_reference_normalization).
    Some test modules replace the stub with a bare module; this
    function re-attaches the constants without disturbing their other
    customizations.
    """
    mod = sys.modules.get("marine_observation_service")
    if mod is None:
        mod = types.ModuleType("marine_observation_service")
        sys.modules["marine_observation_service"] = mod
    if not hasattr(mod, "MarineObservationService"):
        class _StubMarineObservationService:
            pass
        mod.MarineObservationService = _StubMarineObservationService
    if not hasattr(mod, "SCIENTIFIC_NAMES"):
        mod.SCIENTIFIC_NAMES = dict(_SCIENTIFIC_NAMES)


# Run at import time so all test modules see a consistent stub.
_ensure_stub()
