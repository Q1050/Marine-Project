"""Phase 5G lifecycle validation against an isolated clone of the real schema/data."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import types
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import init_db  # noqa: E402


class _ControlledObservationService:
    device = "controlled-test-double"

    def analyze(self, **_kwargs):
        return {
            "observation": {},
            "identification": {
                "status": "accepted",
                "species": "Pterois volitans",
                "nearest_candidate": "Pterois miles",
                "score": 0.96,
                "margin": 0.24,
                "candidates": [{"species": "Pterois volitans", "score": 0.96}],
            },
            "regional_evidence": {"context": "CONTROLLED_INTEGRATION_FIXTURE"},
            "ecological_status": "INVASIVE",
            "decision": "KNOWN_INVASIVE_RECORD",
            "priority": "HIGH",
            "reason": "Deterministic Phase 5G lifecycle fixture.",
        }


service_module = types.ModuleType("marine_observation_service")
service_module.MarineObservationService = _ControlledObservationService
sys.modules.setdefault("marine_observation_service", service_module)

import api  # noqa: E402
from auth_service import hash_password  # noqa: E402
from database import get_db  # noqa: E402
from models import (  # noqa: E402
    AuthSession,
    Jurisdiction,
    NextAreaSnapshotCell,
    NextAreaSnapshotGeneration,
    Observation,
    Organization,
    OrganizationJurisdiction,
    OrganizationMembership,
    Region,
    User,
)
from next_area_prediction_service import (  # noqa: E402
    PREDICTION_VERSION,
    SCORING_FORMULA,
    SUITABILITY_MODEL_VERSION,
    NextAreaPredictionService,
)


ROOT = Path(__file__).resolve().parent
REAL_DB = ROOT / "marine_observations.db"
REAL_UPLOADS = ROOT / "uploads" / "observations"
PASSWORD = "integration-password"


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upload_manifest():
    return [
        (path.name, path.stat().st_size, file_hash(path))
        for path in sorted(REAL_UPLOADS.glob("*")) if path.is_file()
    ]


def auth_header(client, email):
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_user(db, email, role=None, organization=None, platform_admin=False):
    user = User(
        email=email,
        display_name=email.split("@")[0],
        password_hash=hash_password(PASSWORD),
        status="ACTIVE",
        is_platform_admin=platform_admin,
    )
    db.add(user); db.flush()
    if role:
        db.add(OrganizationMembership(
            user_id=user.id, organization_id=organization.id,
            role=role, status="ACTIVE",
        ))
    db.commit()
    return user


def cells(db, generation_id):
    return {
        row.grid_cell_id: (row.monitoring_priority_score, row.priority_band)
        for row in db.query(NextAreaSnapshotCell)
        .filter(NextAreaSnapshotCell.generation_id == generation_id).all()
    }


def snapshot_diff(old, new):
    shared = set(old) & set(new)
    changed = [(cell, new[cell][0] - old[cell][0]) for cell in shared if new[cell][0] != old[cell][0]]
    increases = [item for item in changed if item[1] > 0]
    decreases = [item for item in changed if item[1] < 0]
    return {
        "cells_added": len(set(new) - set(old)),
        "cells_removed": len(set(old) - set(new)),
        "scores_changed": len(changed),
        "bands_changed": sum(old[cell][1] != new[cell][1] for cell in shared),
        "largest_increase": max(increases, key=lambda item: item[1], default=None),
        "largest_decrease": min(decreases, key=lambda item: item[1], default=None),
    }


def test_jamaica_end_to_end_lifecycle_isolated(tmp_path, monkeypatch):
    production_hash_before = file_hash(REAL_DB)
    production_uploads_before = upload_manifest()
    isolated_db = tmp_path / "phase5g.sqlite"
    isolated_upload_root = tmp_path / "uploads"
    isolated_observations = isolated_upload_root / "observations"
    isolated_observations.mkdir(parents=True)
    shutil.copy2(REAL_DB, isolated_db)

    engine = create_engine(
        f"sqlite:///{isolated_db.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(init_db, "engine", engine)
    init_db.initialize_database()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    api.app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(api, "UPLOAD_DIRECTORY", isolated_observations)
    monkeypatch.setattr(api, "service", _ControlledObservationService())

    report = {"inference": "DETERMINISTIC_TEST_DOUBLE; NOT A MODEL-ACCURACY TEST"}
    try:
        with Session() as db:
            jamaica = db.query(Jurisdiction).join(Region).filter(Region.slug == "caribbean", Jurisdiction.slug == "jamaica").one()
            other = Jurisdiction(
                region_id=jamaica.region_id, name="Integration Test Island",
                slug="integration-test-island", country_code="IT", status="ACTIVE",
                center_latitude=12, center_longitude=-60, default_zoom=7,
            )
            db.add(other); db.flush()
            agency = Organization(
                name="Jamaica Marine Monitoring Test Agency",
                slug="phase5g-jamaica-test-agency", organization_type="OTHER", status="ACTIVE",
            )
            unrelated_agency = Organization(
                name="Unrelated Integration Test Agency",
                slug="phase5g-unrelated-test-agency", organization_type="OTHER", status="ACTIVE",
            )
            db.add_all([agency, unrelated_agency]); db.flush()
            db.add_all([
                OrganizationJurisdiction(organization_id=agency.id, jurisdiction_id=jamaica.id, status="ACTIVE"),
                OrganizationJurisdiction(organization_id=unrelated_agency.id, jurisdiction_id=other.id, status="ACTIVE"),
            ])
            db.commit()
            jamaica_id = jamaica.id
            other_id = other.id
            viewer = create_user(db, "phase5g-viewer@example.test", "VIEWER", agency)
            reviewer = create_user(db, "phase5g-reviewer@example.test", "REVIEWER", agency)
            manager = create_user(db, "phase5g-manager@example.test", "MANAGER", agency)
            outsider = create_user(db, "phase5g-outsider@example.test", "REVIEWER", unrelated_agency)
            admin = create_user(db, "phase5g-admin@example.test", platform_admin=True)
            actor_ids = {item.email: item.id for item in (viewer, reviewer, manager, outsider, admin)}

        client = TestClient(api.app)
        headers = {email: auth_header(client, email) for email in actor_ids}
        jamaica_scope = "region_slug=caribbean&jurisdiction_slug=jamaica"
        freshness_url = f"/predictions/species/Pterois%20volitans/next-areas/freshness?prediction_version={PREDICTION_VERSION}&{jamaica_scope}"
        regenerate_url = f"/predictions/species/Pterois%20volitans/next-areas/regenerate?prediction_version={PREDICTION_VERSION}&{jamaica_scope}"
        review_url = "/observations/review-queue?region_slug=caribbean&jurisdiction_slug=jamaica"

        before_freshness = client.get(freshness_url)
        assert before_freshness.status_code == 200

        before_freshness_data = before_freshness.json()

        # The production snapshot may become stale naturally as existing
        # evidence crosses recency-weight boundaries. Phase 5G only requires
        # that no evidence-state mutation has occurred before the controlled
        # observation is introduced.
        assert "EVIDENCE_STATE_CHANGED" not in before_freshness_data["reasons"]
        assert "NEW_ELIGIBLE_EVIDENCE" not in before_freshness_data["reasons"]
        assert "VERIFICATION_CHANGED" not in before_freshness_data["reasons"]

        report["freshness_before"] = before_freshness_data
        hotspot_before = client.get("/analytics/hotspots").json()

        preview = client.get("/geography/resolve", params={"latitude": 18.0, "longitude": -78.0})
        assert preview.status_code == 200 and preview.json()["jurisdiction"]["slug"] == "jamaica"
        report["resolution"] = preview.json()

        before_files = list(isolated_observations.iterdir())
        outside = client.post(
            "/observations/analyze",
                data={"latitude": "0", "longitude": "0", "location_source": "MANUAL"},
            files={"image": ("outside.jpg", b"not-persisted", "image/jpeg")},
        )
        assert outside.status_code == 422
        assert list(isolated_observations.iterdir()) == before_files

        image_path = ROOT / "data" / "ground_species_dataset" / "raw" / "pterois_volitans" / "pterois_volitans_0002.jpg"
        with image_path.open("rb") as image:
            submission = client.post(
                "/observations/analyze",
                data={
                    "latitude": "18.0", "longitude": "-78.0",
                        "jurisdiction_id": str(other_id),
                    "location_source": "DEVICE_GEOLOCATION",
                    "location_accuracy_m": "12.5",
                    "location_captured_at": "2026-08-17T12:00:00Z",
                },
                files={"image": (image_path.name, image, "image/jpeg")},
            )
        assert submission.status_code == 200, submission.text
        observation_id = submission.json()["observation"]["id"]
        assert observation_id == 13
        report["observation_id"] = observation_id

        with Session() as db:
            observation = db.query(Observation).filter_by(id=observation_id).one()
            assert observation.jurisdiction_id == jamaica_id
            assert observation.location_source == "DEVICE_GEOLOCATION"
            assert observation.location_accuracy_m == 12.5
            assert observation.verification_status == "PENDING"
            assert observation.species == "Pterois volitans"
            assert observation.verified_species is None
            stored_filename = observation.image_filename

        stored_path = isolated_observations / stored_filename
        assert stored_path.is_file() and stored_path.stat().st_size == image_path.stat().st_size
        detail = client.get(f"/observations/{observation_id}")
        assert detail.status_code == 200 and detail.json()["observation"]["image_url"] is None
        assert client.get(f"/uploads/observations/{stored_filename}").status_code == 404
        report["image"] = {"stored_private": True, "public_url": None, "legacy_static_status": 404}

        jamaica_map = client.get("/observations/map?region_slug=caribbean&jurisdiction_slug=jamaica").json()
        marker = next(item for item in jamaica_map["markers"] if item["id"] == observation_id)
        assert marker["jurisdiction"] == "jamaica" and marker["verification_status"] == "PENDING"
        other_map = client.get("/observations/map?region_slug=caribbean&jurisdiction_slug=integration-test-island").json()
        assert all(item["id"] != observation_id for item in other_map["markers"])
        report["map_visibility"] = {"jamaica": True, "unrelated": False, "marker": marker}

        assert client.get(review_url).status_code == 401
        assert client.get(review_url, headers=headers[viewer.email]).status_code == 403
        reviewer_queue = client.get(review_url, headers=headers[reviewer.email])
        assert reviewer_queue.status_code == 200
        assert observation_id in {item["id"] for item in reviewer_queue.json()["queue"]}
        assert client.get(review_url, headers=headers[outsider.email]).status_code == 403
        report["review_queue"] = {"eligible": True, "reviewer_count": reviewer_queue.json()["count"]}

        verification_url = f"/observations/{observation_id}/verify"
        verification_payload = {"status": "CONFIRMED", "verified_species": "Pterois volitans", "notes": "Phase 5G controlled verification."}
        authorization = {
            "public_verify": client.patch(verification_url, json=verification_payload).status_code,
            "viewer_verify": client.patch(verification_url, json=verification_payload, headers=headers[viewer.email]).status_code,
            "outsider_verify": client.patch(verification_url, json=verification_payload, headers=headers[outsider.email]).status_code,
        }
        assert authorization == {"public_verify": 401, "viewer_verify": 403, "outsider_verify": 403}
        verified = client.patch(verification_url, json=verification_payload, headers=headers[reviewer.email])
        assert verified.status_code == 200
        with Session() as db:
            observation = db.query(Observation).filter_by(id=observation_id).one()
            assert observation.verification_status == "CONFIRMED"
            assert observation.verified_species == "Pterois volitans"
            assert observation.verified_at is not None
            assert observation.verified_by_user_id == reviewer.id
            assert observation.species == "Pterois volitans" and observation.score == 0.96
        report["verification"] = verified.json()

        hotspot_after = client.get("/analytics/hotspots").json()
        before_by_cell = {(item["latitude"], item["longitude"]): item for item in hotspot_before["hotspots"]}
        after_by_cell = {(item["latitude"], item["longitude"]): item for item in hotspot_after["hotspots"]}
        added_hotspot_cells = set(after_by_cell) - set(before_by_cell)
        report["hotspots"] = {
            "before_cells": hotspot_before["count"], "after_cells": hotspot_after["count"],
            "added_cells": [list(cell) for cell in added_hotspot_cells],
            "controlled_cell": after_by_cell[next(iter(added_hotspot_cells))] if added_hotspot_cells else None,
        }

        stale = client.get(freshness_url)
        assert stale.status_code == 200 and stale.json()["status"] == "STALE"
        assert "EVIDENCE_STATE_CHANGED" in stale.json()["reasons"]
        report["freshness_after"] = stale.json()

        original_regenerate = api.NextAreaPredictionService.regenerate
        auth_calls = []
        def authorized_probe(_self, *_args, **_kwargs):
            auth_calls.append(True)
            return {"generation_id": -1}
        monkeypatch.setattr(api.NextAreaPredictionService, "regenerate", authorized_probe)
        authorization.update({
            "public_regenerate": client.post(regenerate_url).status_code,
            "reviewer_regenerate": client.post(regenerate_url, headers=headers[reviewer.email]).status_code,
            "manager_regenerate": client.post(regenerate_url, headers=headers[manager.email]).status_code,
            "admin_regenerate": client.post(regenerate_url, headers=headers[admin.email]).status_code,
        })
        assert authorization["public_regenerate"] == 401
        assert authorization["reviewer_regenerate"] == 403
        assert authorization["manager_regenerate"] == 200
        assert authorization["admin_regenerate"] == 200
        assert len(auth_calls) == 2
        monkeypatch.setattr(api.NextAreaPredictionService, "regenerate", original_regenerate)
        report["authorization"] = authorization

        with Session() as db:
            old_generation = db.query(NextAreaSnapshotGeneration).filter_by(is_active=True).one()
            old_id = old_generation.id
            old_cells = cells(db, old_id)
        regenerated = client.post(regenerate_url, headers=headers[manager.email])
        assert regenerated.status_code == 200, regenerated.text
        generation_result = regenerated.json()["generation"]
        new_id = generation_result["generation_id"]
        assert new_id != old_id
        with Session() as db:
            generations = db.query(NextAreaSnapshotGeneration).order_by(NextAreaSnapshotGeneration.id).all()
            assert sum(item.is_active for item in generations) == 1
            assert db.query(NextAreaSnapshotGeneration).filter_by(id=old_id).one().status == "SUPERSEDED"
            new_generation = db.query(NextAreaSnapshotGeneration).filter_by(id=new_id).one()
            assert new_generation.status == "ACTIVE" and new_generation.is_active
            assert new_generation.prediction_version == PREDICTION_VERSION
            assert new_generation.suitability_model_version == SUITABILITY_MODEL_VERSION
            assert new_generation.evidence_state_json
            assert new_generation.started_at and new_generation.generated_at and new_generation.completed_at
            new_cells = cells(db, new_id)
        assert generation_result["scoring_formula"] == SCORING_FORMULA
        report["regeneration"] = {
            "old_generation": old_id, "new_generation": new_id,
            "new_cell_count": len(new_cells), "history_count": len(generations),
            "formula": generation_result["scoring_formula"],
        }
        report["snapshot_comparison"] = snapshot_diff(old_cells, new_cells)

        post_freshness = client.get(freshness_url)
        assert post_freshness.status_code == 200 and post_freshness.json()["status"] == "FRESH"
        report["freshness_post_regeneration"] = post_freshness.json()

        service = NextAreaPredictionService()
        with Session() as db:
            active_before_failure = service.summary(db)["generation_id"]
            def controlled_failure(session, *_args, **_kwargs):
                assert service.summary(session)["generation_id"] == active_before_failure
                assert session.query(NextAreaSnapshotGeneration).filter_by(status="BUILDING", is_active=False).count() == 1
                raise RuntimeError("controlled Phase 5G failure")

            with patch.object(service, "_build_snapshot", side_effect=controlled_failure):
                try:
                    service.regenerate(db)
                except RuntimeError:
                    pass
            assert service.summary(db)["generation_id"] == active_before_failure
            failed = db.query(NextAreaSnapshotGeneration).filter_by(status="FAILED").all()
            assert failed and all(not item.is_active for item in failed)
            report["failure_safety"] = {"active_retained": active_before_failure, "failed_generations": len(failed)}

            original = db.query(Observation).filter_by(id=observation_id).one()
            duplicate = Observation(
                jurisdiction_id=original.jurisdiction_id,
                image_filename="phase5g-duplicate.jpg", image_hash=original.image_hash,
                is_possible_duplicate=True, duplicate_of_observation_id=original.id,
                latitude=original.latitude, longitude=original.longitude,
                identification_status=original.identification_status, species=original.species,
                nearest_candidate=original.nearest_candidate, score=original.score, margin=original.margin,
                candidates_json=original.candidates_json, regional_evidence_json=original.regional_evidence_json,
                ecological_status=original.ecological_status, decision=original.decision,
                priority=original.priority, reason=original.reason,
                verification_status="PENDING", created_at=datetime.now(timezone.utc),
            )
            db.add(duplicate); db.commit(); db.refresh(duplicate)
            _, diagnostics, _ = service._build_snapshot(db, "Pterois volitans", PREDICTION_VERSION, datetime.now(timezone.utc))
            assert diagnostics["duplicates_excluded"] >= 1
            duplicate_freshness = service.freshness(db)
            assert duplicate_freshness["status"] == "STALE"
            report["duplicate"] = {
                "id": duplicate.id, "excluded_from_evidence": True,
                "freshness": duplicate_freshness["status"],
            }
        duplicate_queue = client.get(review_url, headers=headers[reviewer.email]).json()["queue"]
        assert any(item["id"] == duplicate.id and item["is_possible_duplicate"] for item in duplicate_queue)
        report["duplicate"]["reviewable"] = True

        assert production_hash_before == file_hash(REAL_DB)
        assert production_uploads_before == upload_manifest()
        report["production_unchanged"] = True
        print("PHASE5G_REPORT=" + json.dumps(report, default=str, sort_keys=True))
    finally:
        api.app.dependency_overrides.clear()
        engine.dispose()
