"""Explicit scientific deployment lifecycle and dependency-event boundary."""
from datetime import datetime, timezone

from early_warning_operations import EarlyWarningOperations
from models import SpeciesProgram, SuitabilityDeployment


class SuitabilityDeploymentGovernance:
    def __init__(self, session):
        self.session = session

    def activate(self, deployment_id, reference):
        row = self.session.get(SuitabilityDeployment, deployment_id)
        if not row:
            raise ValueError("Suitability deployment not found")
        program = self.session.get(SpeciesProgram, row.species_program_id)
        if not program or program.status != "ACTIVE":
            raise ValueError("An active jurisdiction species program is required")
        if row.status == "ACTIVE":
            return row, False
        previous = self.session.query(SuitabilityDeployment).filter(
            SuitabilityDeployment.species_program_id == row.species_program_id,
            SuitabilityDeployment.status == "ACTIVE",
            SuitabilityDeployment.id != row.id,
        ).all()
        for existing in previous:
            existing.status = "SUPERSEDED"
        row.status = "ACTIVE"
        row.activated_at = datetime.now(timezone.utc)
        EarlyWarningOperations(self.session).emit(
            "SUITABILITY_DEPLOYMENT_CHANGED", program.jurisdiction_id,
            program.species_id, dependency_reference=f"deployment:{row.id}:{row.artifact_hash}:{reference}",
            payload={"deployment_id": row.id, "model_version": row.model_version, "state": "ACTIVE", "replaced_deployment_ids": [item.id for item in previous]},
        )
        self.session.flush()
        return row, True

    def deactivate(self, deployment_id, reference):
        row = self.session.get(SuitabilityDeployment, deployment_id)
        if not row:
            raise ValueError("Suitability deployment not found")
        if row.status != "ACTIVE":
            return row, False
        program = self.session.get(SpeciesProgram, row.species_program_id)
        row.status = "INACTIVE"
        EarlyWarningOperations(self.session).emit(
            "SUITABILITY_DEPLOYMENT_CHANGED", program.jurisdiction_id,
            program.species_id, dependency_reference=f"deployment:{row.id}:{row.artifact_hash}:INACTIVE:{reference}",
            payload={"deployment_id": row.id, "model_version": row.model_version, "state": "INACTIVE"},
        )
        self.session.flush()
        return row, True
