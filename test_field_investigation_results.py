from datetime import datetime, timezone

from models import FieldObservation, FieldVisit, Investigation, NextAreaSnapshotGeneration, NextAreaSnapshotCell
from test_investigation_foundation import create_payload, environment  # noqa: F401


def visit_payload(**values):
    payload = {
        "visited_at": datetime.now(timezone.utc).isoformat(),
        "latitude": 18.1, "longitude": -78.1,
        "survey_method": "DIVE_SURVEY", "effort_duration_minutes": 45,
        "target_detection_status": "NOT_DETECTED",
        "area_description": "Reef edge", "notes": "Survey completed.", "status": "DRAFT",
    }
    payload.update(values)
    return payload


def create_investigation(client, headers, organization_id):
    response = client.post("/regions/caribbean/jurisdictions/jamaica/investigations", json=create_payload(organization_id), headers=headers("manager"))
    assert response.status_code == 200
    return response.json()


def test_visit_authorization_and_non_detection_semantics(environment):
    db, client, headers, _, _, organization, _, *_ = environment
    investigation = create_investigation(client, headers, organization.id)
    url = f"/investigations/{investigation['id']}/field-visits"
    assert client.get(url).status_code == 401
    assert client.post(url, json=visit_payload(), headers=headers("viewer")).status_code == 403
    assert client.post(url, json=visit_payload(), headers=headers("reviewer")).status_code == 403
    assert client.post(url, json=visit_payload(), headers=headers("outsider")).status_code == 403
    created = client.post(url, json=visit_payload(), headers=headers("manager"))
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "DRAFT" and body["target_detection_status"] == "NOT_DETECTED"
    assert body["observation_count"] == 0 and "should not be interpreted as confirmed species absence" in body["non_detection_interpretation"]
    assert client.get(url, headers=headers("viewer")).status_code == 200
    assert client.get(url, headers=headers("reviewer")).status_code == 200
    assert client.get(f"/field-visits/{body['id']}", headers=headers("admin")).status_code == 200
    assert db.query(FieldVisit).count() == 1 and db.query(FieldObservation).count() == 0


def test_multiple_visits_detection_values_and_organization_validation(environment):
    db, client, headers, _, _, organization, unrelated, *_ = environment
    investigation = create_investigation(client, headers, organization.id)
    url = f"/investigations/{investigation['id']}/field-visits"
    for detection in ["DETECTED", "NOT_DETECTED", "INCONCLUSIVE"]:
        response = client.post(url, json=visit_payload(target_detection_status=detection), headers=headers("manager"))
        assert response.status_code == 200
    assert client.post(url, json=visit_payload(organization_id=unrelated.id), headers=headers("manager")).status_code == 400
    assert client.post(url, json=visit_payload(target_detection_status="ABSENT"), headers=headers("manager")).status_code == 400
    assert len(db.query(Investigation).one().field_visits) == 3


def test_draft_edit_submit_and_submitted_protection(environment):
    _, client, headers, _, _, organization, *_ = environment
    investigation = create_investigation(client, headers, organization.id)
    visit = client.post(f"/investigations/{investigation['id']}/field-visits", json=visit_payload(), headers=headers("manager")).json()
    patched = client.patch(f"/field-visits/{visit['id']}", json={"effort_duration_minutes": 60, "target_detection_status": "INCONCLUSIVE"}, headers=headers("manager"))
    assert patched.status_code == 200 and patched.json()["effort_duration_minutes"] == 60
    submitted = client.post(f"/field-visits/{visit['id']}/submit", headers=headers("manager"))
    assert submitted.status_code == 200 and submitted.json()["status"] == "SUBMITTED" and submitted.json()["submitted_at"]
    assert client.patch(f"/field-visits/{visit['id']}", json={"notes": "changed"}, headers=headers("manager")).status_code == 400
    assert client.post(f"/field-visits/{visit['id']}/observations", json={"scientific_name": "Pterois volitans"}, headers=headers("manager")).status_code == 400


def test_field_observations_preserve_nullable_count_and_precise_location(environment):
    db, client, headers, _, _, organization, *_ = environment
    investigation = create_investigation(client, headers, organization.id)
    visit = client.post(f"/investigations/{investigation['id']}/field-visits", json=visit_payload(target_detection_status="DETECTED"), headers=headers("manager")).json()
    url = f"/field-visits/{visit['id']}/observations"
    first = client.post(url, json={"scientific_name": "Pterois volitans", "count_observed": None, "latitude": 18.2, "longitude": -78.0}, headers=headers("manager"))
    second = client.post(url, json={"scientific_name": "Pterois miles", "count_observed": 2}, headers=headers("manager"))
    assert first.status_code == second.status_code == 200
    assert first.json()["count_observed"] is None and first.json()["latitude"] != visit["latitude"]
    listed = client.get(url, headers=headers("viewer")).json()
    assert listed["count"] == 2 and db.query(FieldObservation).count() == 2


def test_location_and_investigation_status_rules(environment):
    _, client, headers, _, _, organization, *_ = environment
    completed = create_investigation(client, headers, organization.id)
    client.post(f"/investigations/{completed['id']}/status", json={"status": "IN_PROGRESS"}, headers=headers("manager"))
    client.post(f"/investigations/{completed['id']}/status", json={"status": "COMPLETED"}, headers=headers("manager"))
    assert client.post(f"/investigations/{completed['id']}/field-visits", json=visit_payload(), headers=headers("manager")).status_code == 400
    cancelled = create_investigation(client, headers, organization.id)
    client.post(f"/investigations/{cancelled['id']}/status", json={"status": "CANCELLED"}, headers=headers("manager"))
    assert client.post(f"/investigations/{cancelled['id']}/field-visits", json=visit_payload(), headers=headers("manager")).status_code == 400
    active = create_investigation(client, headers, organization.id)
    assert client.post(f"/investigations/{active['id']}/field-visits", json=visit_payload(latitude=12, longitude=-60), headers=headers("manager")).status_code == 400
    assert client.post(f"/investigations/{active['id']}/field-visits", json=visit_payload(latitude=100), headers=headers("manager")).status_code == 400


def test_scientific_pipeline_firewall(environment):
    db, client, headers, _, _, organization, _, _, _, generation, _ = environment
    investigation = create_investigation(client, headers, organization.id)
    generation_state = (generation.id, generation.status, generation.is_active, generation.evidence_state_json)
    cell_count = db.query(NextAreaSnapshotCell).count()
    visit = client.post(f"/investigations/{investigation['id']}/field-visits", json=visit_payload(target_detection_status="DETECTED"), headers=headers("manager")).json()
    client.post(f"/field-visits/{visit['id']}/observations", json={"scientific_name": "Pterois volitans", "count_observed": 1}, headers=headers("manager"))
    db.refresh(generation)
    assert (generation.id, generation.status, generation.is_active, generation.evidence_state_json) == generation_state
    assert db.query(NextAreaSnapshotGeneration).count() == 1
    assert db.query(NextAreaSnapshotCell).count() == cell_count
