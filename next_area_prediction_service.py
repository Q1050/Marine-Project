import json
import threading
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy.exc import IntegrityError

from geographic_utils import haversine_km
from models import HabitatSuitabilityV3GridCell, NextAreaSnapshotCell, NextAreaSnapshotGeneration, Observation
from monitoring_engine import MonitoringEngine

PREDICTION_VERSION = "pterois-volitans-next-area-v1"
SUITABILITY_MODEL_VERSION = "pterois-volitans-suitability-v3"
SPECIES = "Pterois volitans"
DISCLAIMER = (
    "This is a monitoring-priority score combining habitat suitability and "
    "current observation evidence. It is not a probability that the species "
    "will spread to or occur in the cell."
)
SCORING_FORMULA = "0.55 * suitability_score + 0.45 * current_evidence_score"
CURRENT_EVIDENCE_FORMULA = "max(verification_weight * recency_weight * distance_weight)"
_regeneration_lock = threading.Lock()


class RegenerationInProgressError(RuntimeError):
    pass


class NextAreaPredictionService:
    def __init__(self):
        self.monitoring_engine = MonitoringEngine()

    @staticmethod
    def _utc(value):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def recency_weight(age_days):
        if age_days <= 7:
            return 1.0
        if age_days <= 30:
            return 0.8
        if age_days <= 90:
            return 0.5
        if age_days <= 365:
            return 0.25
        return 0.1

    @staticmethod
    def distance_weight(distance_km):
        if distance_km <= 10:
            return 1.0
        if distance_km <= 25:
            return 0.8
        if distance_km <= 50:
            return 0.5
        if distance_km <= 100:
            return 0.2
        return 0.0

    @staticmethod
    def priority_band(score):
        if score < 0.2:
            return "VERY_LOW"
        if score < 0.4:
            return "LOW"
        if score < 0.6:
            return "MODERATE"
        if score < 0.8:
            return "HIGH"
        return "VERY_HIGH"

    @staticmethod
    def displayed_species(observation):
        if observation.verification_status in {"CONFIRMED", "CORRECTED"} and observation.verified_species:
            return observation.verified_species
        return observation.species

    def _active_generation(self, db, scientific_name, prediction_version, species_program_id=None):
        query = db.query(NextAreaSnapshotGeneration).filter(
            NextAreaSnapshotGeneration.scientific_name == scientific_name,
            NextAreaSnapshotGeneration.prediction_version == prediction_version,
            NextAreaSnapshotGeneration.is_active.is_(True),
            NextAreaSnapshotGeneration.status == "ACTIVE",
        )
        if species_program_id is not None:
            query = query.filter(NextAreaSnapshotGeneration.species_program_id == species_program_id)
        return query.one_or_none()

    def _evidence(self, db, scientific_name, generated_at, jurisdiction_id=None):
        duplicates_excluded = 0
        evidence = []
        query = db.query(Observation)
        if jurisdiction_id is not None:
            query = query.filter(Observation.jurisdiction_id == jurisdiction_id)
        for observation in query.order_by(Observation.id).all():
            if self.displayed_species(observation) != scientific_name:
                continue
            if observation.is_possible_duplicate or observation.duplicate_of_observation_id:
                duplicates_excluded += 1
                continue
            level = self.monitoring_engine.classify_evidence(
                observation.identification_status, observation.verification_status
            )
            weight = {"CONFIRMED": 1.0, "AI_SUPPORTED": 0.6}.get(level, 0.0)
            if weight == 0.0:
                continue
            created_at = self._utc(observation.created_at)
            age_days = max(0.0, (generated_at - created_at).total_seconds() / 86400)
            evidence.append({
                "id": observation.id,
                "latitude": observation.latitude,
                "longitude": observation.longitude,
                "level": level,
                "evidence_weight": weight,
                "recency_weight": self.recency_weight(age_days),
                "age_days": age_days,
                "created_at": created_at,
            })
        return evidence, duplicates_excluded

    def _evidence_state(self, db, scientific_name, jurisdiction_id=None):
        state = []
        query = db.query(Observation)
        if jurisdiction_id is not None:
            query = query.filter(Observation.jurisdiction_id == jurisdiction_id)
        for observation in query.order_by(Observation.id).all():
            if observation.species != scientific_name and observation.verified_species != scientific_name:
                continue
            state.append({
                "id": observation.id,
                "species": observation.species,
                "verified_species": observation.verified_species,
                "identification_status": observation.identification_status,
                "verification_status": observation.verification_status,
                "is_possible_duplicate": bool(observation.is_possible_duplicate),
                "duplicate_of_observation_id": observation.duplicate_of_observation_id,
                "latitude": observation.latitude,
                "longitude": observation.longitude,
                "created_at": self._utc(observation.created_at).isoformat(),
                "verified_at": self._utc(observation.verified_at).isoformat() if observation.verified_at else None,
            })
        return state

    def score_cell(self, cell, evidence):
        contributions = []
        for item in evidence:
            distance = haversine_km(cell.latitude, cell.longitude, item["latitude"], item["longitude"])
            distance_weight = self.distance_weight(distance)
            contributions.append(item | {
                "distance_km": distance,
                "distance_weight": distance_weight,
                "contribution": item["evidence_weight"] * item["recency_weight"] * distance_weight,
            })
        nearest = min(contributions, key=lambda item: (item["distance_km"], item["id"]), default=None)
        nearby = [item for item in contributions if item["distance_weight"] > 0]
        strongest = max(
            nearby,
            key=lambda item: (item["contribution"], -item["distance_km"], -item["id"]),
            default=None,
        )
        current_score = strongest["contribution"] if strongest else 0.0
        observation_score = strongest["evidence_weight"] * strongest["distance_weight"] if strongest else 0.0
        recent_score = strongest["recency_weight"] * strongest["distance_weight"] if strongest else 0.0
        priority = 0.55 * cell.suitability_score + 0.45 * current_score
        reasons = []
        if cell.suitability_score >= 0.6:
            reasons.append("HIGH_HABITAT_SUITABILITY")
        if strongest and strongest["distance_km"] <= 100 and strongest["recency_weight"] >= 0.8:
            reasons.append(
                "NEAR_RECENT_CONFIRMED_SIGHTING" if strongest["level"] == "CONFIRMED"
                else "NEAR_RECENT_AI_SUPPORTED_SIGHTING"
            )
        return {
            "nearest_km": nearest["distance_km"] if nearest else None,
            "observation_score": observation_score,
            "recent_score": recent_score,
            "current_score": current_score,
            "priority": priority,
            "band": self.priority_band(priority),
            "source_ids": sorted(item["id"] for item in nearby),
            "evidence": {
                "confirmed": sum(item["level"] == "CONFIRMED" for item in nearby),
                "ai_supported": sum(item["level"] == "AI_SUPPORTED" for item in nearby),
            },
            "reasons": reasons,
        }

    def _build_snapshot(self, db, scientific_name, prediction_version, generated_at, suitability_deployment_id=None, jurisdiction_id=None):
        grid = db.query(HabitatSuitabilityV3GridCell).filter(
            HabitatSuitabilityV3GridCell.scientific_name == scientific_name,
            HabitatSuitabilityV3GridCell.model_version == SUITABILITY_MODEL_VERSION,
            HabitatSuitabilityV3GridCell.prediction_status == "SCORED",
        )
        if suitability_deployment_id is not None:
            grid = grid.filter(HabitatSuitabilityV3GridCell.suitability_deployment_id == suitability_deployment_id)
        grid = grid.order_by(HabitatSuitabilityV3GridCell.grid_cell_id).all()
        if not grid:
            raise ValueError("The suitability-v3 Jamaica grid is not available")
        evidence, duplicates_excluded = self._evidence(db, scientific_name, generated_at, jurisdiction_id)
        occupied = {
            f"{int(np.floor(item['latitude'] / 0.1))}:{int(np.floor(item['longitude'] / 0.1))}"
            for item in evidence
        }
        rows = []
        for cell in grid:
            if cell.grid_cell_id in occupied:
                continue
            result = self.score_cell(cell, evidence)
            rows.append({
                "scientific_name": scientific_name,
                "prediction_version": prediction_version,
                "grid_cell_id": cell.grid_cell_id,
                "latitude": cell.latitude,
                "longitude": cell.longitude,
                "suitability_score": cell.suitability_score,
                "distance_from_nearest_current_evidence_km": result["nearest_km"],
                "observation_evidence_score": result["observation_score"],
                "recent_activity_score": result["recent_score"],
                "current_evidence_score": result["current_score"],
                "monitoring_priority_score": result["priority"],
                "priority_band": result["band"],
                "source_observation_ids_json": json.dumps(result["source_ids"]),
                "evidence_json": json.dumps(result["evidence"]),
                "reason_codes_json": json.dumps(result["reasons"]),
                "generated_at": generated_at,
            })
        if not rows:
            raise ValueError("No complete monitoring-priority cells were generated")
        scores = [row["monitoring_priority_score"] for row in rows]
        diagnostics = {
            "observations_eligible_as_current_evidence": len(evidence),
            "duplicates_excluded": duplicates_excluded,
            "confirmed_observations_used": sum(item["level"] == "CONFIRMED" for item in evidence),
            "ai_supported_observations_used": sum(item["level"] == "AI_SUPPORTED" for item in evidence),
            "candidate_cells_evaluated": len(grid),
            "cells_excluded_as_currently_occupied": len(grid) - len(rows),
            "recommendation_cells": len(rows),
            "score": {"min": min(scores), "median": float(np.median(scores)), "max": max(scores)},
            "priority_band_counts": {
                band: sum(row["priority_band"] == band for row in rows)
                for band in ("VERY_LOW", "LOW", "MODERATE", "HIGH", "VERY_HIGH")
            },
        }
        return rows, diagnostics, self._evidence_state(db, scientific_name, jurisdiction_id)

    def generate(self, db, scientific_name=SPECIES, prediction_version=PREDICTION_VERSION, now=None, species_program_id=None, suitability_deployment_id=None, jurisdiction_id=None):
        if self._active_generation(db, scientific_name, prediction_version, species_program_id) is not None:
            return self.summary(db, scientific_name, prediction_version, species_program_id)
        return self.regenerate(db, scientific_name, prediction_version, now, species_program_id, suitability_deployment_id, jurisdiction_id)

    def regenerate(self, db, scientific_name=SPECIES, prediction_version=PREDICTION_VERSION, now=None, species_program_id=None, suitability_deployment_id=None, jurisdiction_id=None):
        if not _regeneration_lock.acquire(blocking=False):
            raise RegenerationInProgressError("Monitoring-priority regeneration is already in progress.")
        building_id = None
        try:
            started_at = self._utc(now or datetime.now(timezone.utc))
            building = NextAreaSnapshotGeneration(
                scientific_name=scientific_name,
                species_program_id=species_program_id,
                suitability_deployment_id=suitability_deployment_id,
                prediction_version=prediction_version,
                suitability_model_version=SUITABILITY_MODEL_VERSION,
                status="BUILDING",
                is_active=False,
                diagnostics_json="{}",
                started_at=started_at,
            )
            db.add(building)
            try:
                db.commit()
            except IntegrityError as error:
                db.rollback()
                raise RegenerationInProgressError("Monitoring-priority regeneration is already in progress.") from error
            db.refresh(building)
            building_id = building.id
            rows, diagnostics, evidence_state = self._build_snapshot(
                db, scientific_name, prediction_version, started_at,
                suitability_deployment_id=suitability_deployment_id,
                jurisdiction_id=jurisdiction_id,
            )
            if diagnostics["recommendation_cells"] != len(rows):
                raise RuntimeError("Generated snapshot failed cell-count validation")
            previous = self._active_generation(db, scientific_name, prediction_version, species_program_id)
            for values in rows:
                db.add(NextAreaSnapshotCell(generation_id=building_id, **values))
            db.flush()
            count = db.query(NextAreaSnapshotCell).filter(NextAreaSnapshotCell.generation_id == building_id).count()
            if count != len(rows):
                raise RuntimeError("Replacement snapshot was not persisted completely")
            if previous is not None:
                previous.is_active = False
                previous.status = "SUPERSEDED"
                # Release the partial unique active-version slot inside this
                # transaction before activating the complete replacement.
                db.flush()
            building = db.query(NextAreaSnapshotGeneration).filter(NextAreaSnapshotGeneration.id == building_id).one()
            building.status = "ACTIVE"
            building.is_active = True
            building.diagnostics_json = json.dumps(diagnostics)
            building.evidence_state_json = json.dumps(evidence_state, sort_keys=True)
            building.generated_at = started_at
            building.completed_at = datetime.now(timezone.utc)
            db.commit()
            return self.summary(db, scientific_name, prediction_version)
        except RegenerationInProgressError:
            raise
        except Exception:
            db.rollback()
            if building_id is not None:
                failed = db.query(NextAreaSnapshotGeneration).filter(
                    NextAreaSnapshotGeneration.id == building_id
                ).one_or_none()
                if failed is not None and failed.status == "BUILDING":
                    failed.status = "FAILED"
                    failed.completed_at = datetime.now(timezone.utc)
                    db.commit()
            raise
        finally:
            _regeneration_lock.release()

    def _next_recency_boundary(self, evidence, now):
        future = [
            item["created_at"] + timedelta(days=days)
            for item in evidence for days in (7, 30, 90, 365)
            if item["created_at"] + timedelta(days=days) > now
        ]
        return min(future) if future else None

    def freshness(self, db, scientific_name=SPECIES, prediction_version=PREDICTION_VERSION, now=None, jurisdiction_id=None, species_program_id=None):
        generation = self._active_generation(db, scientific_name, prediction_version, species_program_id)
        if generation is None or generation.generated_at is None:
            return None
        checked_at = self._utc(now or datetime.now(timezone.utc))
        generated_at = self._utc(generation.generated_at)
        evidence, _ = self._evidence(db, scientific_name, checked_at, jurisdiction_id)
        stale_reasons, unknown_reasons, changed_ids, change_times = [], [], set(), []
        baseline = json.loads(generation.evidence_state_json) if generation.evidence_state_json else None
        current_state = self._evidence_state(db, scientific_name, jurisdiction_id)
        if baseline is None:
            unknown_reasons.append("LEGACY_EVIDENCE_STATE_UNAVAILABLE")
        elif baseline != current_state:
            stale_reasons.append("EVIDENCE_STATE_CHANGED")
            old = {item["id"]: item for item in baseline}
            new = {item["id"]: item for item in current_state}
            changed_ids.update(identifier for identifier in set(old) | set(new) if old.get(identifier) != new.get(identifier))
        candidates = db.query(Observation).filter(
            (Observation.species == scientific_name) | (Observation.verified_species == scientific_name)
        )
        if jurisdiction_id is not None:
            candidates = candidates.filter(Observation.jurisdiction_id == jurisdiction_id)
        candidates = candidates.all()
        for observation in candidates:
            created_at = self._utc(observation.created_at)
            verified_at = self._utc(observation.verified_at)
            if created_at > generated_at and self.displayed_species(observation) == scientific_name:
                level = self.monitoring_engine.classify_evidence(
                    observation.identification_status, observation.verification_status
                )
                if level in {"CONFIRMED", "AI_SUPPORTED"} and not observation.is_possible_duplicate and not observation.duplicate_of_observation_id:
                    stale_reasons.append("NEW_ELIGIBLE_EVIDENCE")
                    changed_ids.add(observation.id)
                    change_times.append(created_at)
            if verified_at and verified_at > generated_at:
                stale_reasons.append("VERIFICATION_CHANGED")
                changed_ids.add(observation.id)
                change_times.append(verified_at)
            if baseline is None and observation.verification_status != "PENDING" and observation.verified_at is None:
                unknown_reasons.append("LEGACY_VERIFICATION_TIMESTAMP_UNKNOWN")
        for item in evidence:
            generated_age = max(0.0, (generated_at - item["created_at"]).total_seconds() / 86400)
            current_age = max(0.0, (checked_at - item["created_at"]).total_seconds() / 86400)
            if self.recency_weight(generated_age) != self.recency_weight(current_age):
                stale_reasons.append("RECENCY_BUCKET_CHANGED")
                changed_ids.add(item["id"])
        stale_reasons = list(dict.fromkeys(stale_reasons))
        unknown_reasons = list(dict.fromkeys(unknown_reasons))
        status = "STALE" if stale_reasons else ("UNKNOWN" if unknown_reasons else "FRESH")
        reasons = stale_reasons if stale_reasons else unknown_reasons
        next_boundary = self._next_recency_boundary(evidence, checked_at)
        return {
            "species": scientific_name,
            "prediction_version": prediction_version,
            "generation_id": generation.id,
            "generated_at": generated_at.isoformat(),
            "status": status,
            "checked_at": checked_at.isoformat(),
            "reasons": reasons,
            "relevant_changes_since_generation": len(changed_ids),
            "latest_relevant_change_at": max(change_times).isoformat() if change_times else None,
            "next_recency_boundary_at": next_boundary.isoformat() if next_boundary else None,
        }

    def _row(self, row, observations=None):
        nearby_ids = json.loads(row.source_observation_ids_json)
        contributions = []
        for observation_id in nearby_ids:
            observation = (observations or {}).get(observation_id)
            if observation is None:
                continue
            level = self.monitoring_engine.classify_evidence(
                observation.identification_status, observation.verification_status
            )
            verification_weight = {"CONFIRMED": 1.0, "AI_SUPPORTED": 0.6}.get(level, 0.0)
            if verification_weight == 0:
                continue
            created_at, generated_at = self._utc(observation.created_at), self._utc(row.generated_at)
            recency_weight = self.recency_weight(max(0.0, (generated_at - created_at).total_seconds() / 86400))
            distance = haversine_km(row.latitude, row.longitude, observation.latitude, observation.longitude)
            distance_weight = self.distance_weight(distance)
            contributions.append({
                "id": observation.id, "distance": distance,
                "verification_weight": verification_weight,
                "recency_weight": recency_weight, "distance_weight": distance_weight,
                "score": verification_weight * recency_weight * distance_weight,
            })
        contributor = max(contributions, key=lambda item: (item["score"], -item["distance"], -item["id"]), default=None)
        return {
            "species": row.scientific_name, "latitude": row.latitude, "longitude": row.longitude,
            "grid_cell_id": row.grid_cell_id, "suitability_score": row.suitability_score,
            "distance_from_nearest_current_evidence_km": row.distance_from_nearest_current_evidence_km,
            "nearest_evidence_km": row.distance_from_nearest_current_evidence_km,
            "observation_evidence_score": row.observation_evidence_score,
            "recent_activity_score": row.recent_activity_score,
            "current_evidence_score": row.current_evidence_score,
            "monitoring_priority_score": row.monitoring_priority_score,
            "priority_band": row.priority_band,
            "source_observation_ids": nearby_ids, "nearby_observation_ids": nearby_ids,
            "contributing_observation_id": contributor["id"] if contributor else None,
            "contributing_observation_distance_km": contributor["distance"] if contributor else None,
            "contributing_verification_weight": contributor["verification_weight"] if contributor else None,
            "contributing_recency_weight": contributor["recency_weight"] if contributor else None,
            "contributing_distance_weight": contributor["distance_weight"] if contributor else None,
            "contributing_evidence_score": contributor["score"] if contributor else 0.0,
            "evidence": json.loads(row.evidence_json), "reason_codes": json.loads(row.reason_codes_json),
            "prediction_version": row.prediction_version, "generation_id": row.generation_id,
            "generated_at": row.generated_at.isoformat(),
        }

    def recommendations(self, db, scientific_name=SPECIES, prediction_version=PREDICTION_VERSION, limit=20, species_program_id=None):
        generation = self._active_generation(db, scientific_name, prediction_version, species_program_id)
        if generation is None:
            return None
        rows = db.query(NextAreaSnapshotCell).filter(NextAreaSnapshotCell.generation_id == generation.id).order_by(
            NextAreaSnapshotCell.monitoring_priority_score.desc(), NextAreaSnapshotCell.grid_cell_id
        ).limit(limit).all()
        observation_ids = {identifier for row in rows for identifier in json.loads(row.source_observation_ids_json)}
        observations = {item.id: item for item in db.query(Observation).filter(Observation.id.in_(observation_ids)).all()} if observation_ids else {}
        return {
            "species": scientific_name, "prediction_version": prediction_version,
            "generation_id": generation.id, "interpretation": DISCLAIMER,
            "scoring_formula": SCORING_FORMULA, "current_evidence_formula": CURRENT_EVIDENCE_FORMULA,
            "priority_band_thresholds": {
                "VERY_LOW": "0.00-<0.20", "LOW": "0.20-<0.40", "MODERATE": "0.40-<0.60",
                "HIGH": "0.60-<0.80", "VERY_HIGH": "0.80-1.00",
            },
            "count": len(rows), "cells": [self._row(row, observations) for row in rows],
        }

    def summary(self, db, scientific_name=SPECIES, prediction_version=PREDICTION_VERSION, species_program_id=None):
        generation = self._active_generation(db, scientific_name, prediction_version, species_program_id)
        if generation is None:
            return None
        return {
            "species": scientific_name, "prediction_version": prediction_version,
            "generation_id": generation.id,
            "suitability_model_version": generation.suitability_model_version,
            "generated_at": generation.generated_at.isoformat(), "interpretation": DISCLAIMER,
            "scoring_formula": SCORING_FORMULA, "current_evidence_formula": CURRENT_EVIDENCE_FORMULA,
            "evidence_weights": {"CONFIRMED": 1.0, "AI_SUPPORTED": 0.6, "UNRESOLVED": 0.0},
            "recency_weights": {"0-7_days": 1.0, "8-30_days": 0.8, "31-90_days": 0.5, "91-365_days": 0.25, ">365_days": 0.1},
            "distance_weights_km": {"0-10": 1.0, ">10-25": 0.8, ">25-50": 0.5, ">50-100": 0.2, ">100": 0.0},
            "diagnostics": json.loads(generation.diagnostics_json),
        }
