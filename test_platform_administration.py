from models import AuthSession, HistoricalOccurrence, Investigation, NextAreaSnapshotCell, NextAreaSnapshotGeneration, Observation, Organization, OrganizationJurisdiction, OrganizationMembership, User
from test_investigation_foundation import create_payload, environment  # noqa: F401


def test_admin_authorization_region_and_jurisdiction_registry(environment):
    db, client, headers, jamaica, _, organization, *_ = environment
    assert client.post("/admin/regions", json={"name": "Test Region", "slug": "test-region"}).status_code == 401
    assert client.post("/admin/regions", json={"name": "Test Region", "slug": "test-region"}, headers=headers("manager")).status_code == 403
    region = client.post("/admin/regions", json={"name": "Test Region", "slug": "test-region"}, headers=headers("admin"))
    assert region.status_code == 200
    assert client.post("/admin/regions", json={"name": "Duplicate", "slug": "test-region"}, headers=headers("admin")).status_code == 409
    edited = client.patch(f"/admin/regions/{region.json()['id']}", json={"name": "Edited Region"}, headers=headers("admin"))
    assert edited.status_code == 200 and edited.json()["name"] == "Edited Region"
    jurisdiction = client.post("/admin/jurisdictions", json={"region_id": region.json()["id"], "name": "Test Marine Authority", "slug": "test-authority", "country_code": "TT", "center_latitude": 10, "center_longitude": -60, "default_zoom": 7}, headers=headers("admin"))
    assert jurisdiction.status_code == 200 and jurisdiction.json()["region"]["id"] == region.json()["id"]
    duplicate = client.post("/admin/jurisdictions", json={"region_id": region.json()["id"], "name": "Duplicate", "slug": "test-authority", "country_code": "TT", "center_latitude": 10, "center_longitude": -60, "default_zoom": 7}, headers=headers("admin"))
    assert duplicate.status_code == 409
    observation_count = db.query(Observation).count()
    client.patch(f"/admin/regions/{region.json()['id']}", json={"status": "INACTIVE"}, headers=headers("admin"))
    assert db.query(Observation).count() == observation_count and jamaica.status == "ACTIVE" and organization.status == "ACTIVE"


def test_organization_participation_and_immediate_access_changes(environment):
    db, client, headers, jamaica, _, _, _, *_ = environment
    organization = client.post("/admin/organizations", json={"name": "Test Marine Institute", "slug": "test-marine-institute", "organization_type": "RESEARCH_INSTITUTION"}, headers=headers("admin"))
    assert organization.status_code == 200
    assert client.post("/admin/organizations", json={"name": "Duplicate", "slug": "test-marine-institute", "organization_type": "OTHER"}, headers=headers("admin")).status_code == 409
    linked = client.post(f"/admin/organizations/{organization.json()['id']}/jurisdictions", json={"jurisdiction_id": jamaica.id}, headers=headers("admin"))
    assert linked.status_code == 200 and linked.json()["jurisdictions"][0]["relationship_status"] == "ACTIVE"
    assert client.post(f"/admin/organizations/{organization.json()['id']}/jurisdictions", json={"jurisdiction_id": jamaica.id}, headers=headers("admin")).status_code == 409
    user = client.post("/admin/users", json={"email": "new.manager@test.invalid", "display_name": "New Manager", "initial_password": "temporary-password"}, headers=headers("admin")).json()
    client.post(f"/admin/users/{user['id']}/memberships", json={"organization_id": organization.json()["id"], "role": "MANAGER"}, headers=headers("admin"))
    login = client.post("/auth/login", json={"email": "new.manager@test.invalid", "password": "temporary-password"})
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/regions/caribbean/jurisdictions/jamaica/investigations", headers=user_headers).status_code == 200
    client.patch(f"/admin/organizations/{organization.json()['id']}", json={"status": "INACTIVE"}, headers=headers("admin"))
    assert client.get("/regions/caribbean/jurisdictions/jamaica/investigations", headers=user_headers).status_code == 403
    assert db.query(OrganizationJurisdiction).filter_by(organization_id=organization.json()["id"]).count() == 1


def test_user_provisioning_membership_roles_and_session_revocation(environment):
    db, client, headers, _, _, organization, *_ = environment
    created = client.post("/admin/users", json={"email": "trusted@test.invalid", "display_name": "Trusted User", "initial_password": "temporary-password"}, headers=headers("admin"))
    assert created.status_code == 200 and "password_hash" not in created.json() and "initial_password" not in created.json()
    stored = db.query(User).filter_by(id=created.json()["id"]).one()
    assert stored.password_hash != "temporary-password" and stored.password_hash.startswith("scrypt$")
    assert client.post("/admin/users", json={"email": "trusted@test.invalid", "display_name": "Duplicate", "initial_password": "temporary-password"}, headers=headers("admin")).status_code == 409
    membership = client.post(f"/admin/users/{stored.id}/memberships", json={"organization_id": organization.id, "role": "VIEWER"}, headers=headers("admin"))
    assert membership.status_code == 200 and membership.json()["memberships"][0]["role"] == "VIEWER"
    assert client.post(f"/admin/users/{stored.id}/memberships", json={"organization_id": organization.id, "role": "REVIEWER"}, headers=headers("admin")).status_code == 409
    membership_id = membership.json()["memberships"][0]["id"]
    changed = client.patch(f"/admin/memberships/{membership_id}", json={"role": "REVIEWER"}, headers=headers("admin"))
    assert changed.status_code == 200 and changed.json()["memberships"][0]["role"] == "REVIEWER"
    login = client.post("/auth/login", json={"email": "trusted@test.invalid", "password": "temporary-password"})
    active_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/auth/me", headers=active_headers).status_code == 200
    deactivated = client.patch(f"/admin/users/{stored.id}", json={"status": "INACTIVE"}, headers=headers("admin"))
    assert deactivated.status_code == 200
    assert client.get("/auth/me", headers=active_headers).status_code == 401
    assert client.post("/auth/login", json={"email": "trusted@test.invalid", "password": "temporary-password"}).status_code == 401
    assert db.query(AuthSession).filter_by(user_id=stored.id, revoked_at=None).count() == 0


def test_boundary_inspection_excludes_geometry_and_preserves_hash(environment):
    db, client, headers, jamaica, *_ = environment
    boundary = jamaica.boundaries[0]; original = (boundary.geometry_json, boundary.geometry_hash)
    response = client.get(f"/admin/jurisdictions/{jamaica.id}/boundaries", headers=headers("admin"))
    assert response.status_code == 200 and response.json()["geometry_editing_supported"] is False
    assert "geometry_json" not in response.text and response.json()["boundaries"][0]["source"] == "test"
    db.refresh(boundary); assert (boundary.geometry_json, boundary.geometry_hash) == original


def test_admin_scientific_and_historical_firewall(environment):
    db, client, headers, _, _, organization, *_ , generation, cell = environment
    before = {"observations": db.query(Observation).count(), "historical": db.query(HistoricalOccurrence).count(), "generations": db.query(NextAreaSnapshotGeneration).count(), "cells": db.query(NextAreaSnapshotCell).count(), "generation": (generation.id, generation.status, generation.is_active, generation.evidence_state_json), "cell": (cell.id, cell.monitoring_priority_score)}
    investigation = client.post("/regions/caribbean/jurisdictions/jamaica/investigations", json=create_payload(organization.id), headers=headers("manager")).json()
    client.patch(f"/admin/organizations/{organization.id}", json={"name": "Renamed Historical Agency"}, headers=headers("admin"))
    db.refresh(generation); db.refresh(cell)
    assert db.query(Investigation).filter_by(id=investigation["id"]).one().assigned_organization_id == organization.id
    assert db.query(Observation).count() == before["observations"] and db.query(HistoricalOccurrence).count() == before["historical"]
    assert db.query(NextAreaSnapshotGeneration).count() == before["generations"] and db.query(NextAreaSnapshotCell).count() == before["cells"]
    assert (generation.id, generation.status, generation.is_active, generation.evidence_state_json) == before["generation"]
    assert (cell.id, cell.monitoring_priority_score) == before["cell"]
