import enum
from dataclasses import dataclass

class ReadinessStatus(str, enum.Enum):
    READY="READY"; PARTIAL="PARTIAL"; BLOCKED="BLOCKED"; NOT_APPLICABLE="NOT_APPLICABLE"; REVIEW_REQUIRED="REVIEW_REQUIRED"

@dataclass(frozen=True)
class ReadinessDimension:
    name:str; status:ReadinessStatus; reason:str|None=None

@dataclass(frozen=True)
class JurisdictionScientificReadiness:
    jurisdiction_id:int; operation:str; overall_status:ReadinessStatus; dimensions:tuple[ReadinessDimension,...]

SPECIES_BASELINE_PREPARE_CONTRACT={
 "endpoint":"POST /admin/regions/{region_id}/species-baseline/prepare","implemented":False,
 "output_granularity":"jurisdiction_x_taxon",
 "dimensions":["geographic_boundary_ready","taxonomy_baseline_available","occurrence_evidence_available","ecological_status_available","dataset_applicability_approved","controlled_provenance_available","model_prerequisites_available","scientific_review_satisfied"],
 "rule":"regional ecological status is never copied to jurisdictions"
}
