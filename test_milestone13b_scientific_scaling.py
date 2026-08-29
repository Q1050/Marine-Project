import json
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import (EcologicalStatusAssertion, EcologicalStatusCandidate, EcologicalStatusPreparation, GovernedOccurrenceEvidence, Jurisdiction,
                    JurisdictionBoundary, Observation, Region, RegionalTaxonRegistry,
                    ScientificDataset, ScientificDatasetApplicability, Species,
                    SpeciesJurisdictionStatus, SpeciesProgram, SuitabilityDeployment,
                    TrainingRun, User)
from regional_scientific_scaling import RegionalScientificScalingService


def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db, jurisdictions=3, taxa=2):
    region = Region(name="Caribbean", slug="caribbean", status="ACTIVE"); db.add(region); db.flush()
    js=[]
    for index in range(jurisdictions):
        j=Jurisdiction(region_id=region.id,name=f"Jurisdiction {index}",slug=f"j-{index}",country_code=f"{index:02}"[-2:],status="ACTIVE",center_latitude=18,center_longitude=-77,default_zoom=7)
        db.add(j);db.flush();js.append(j)
        db.add(JurisdictionBoundary(jurisdiction_id=j.id,boundary_type="MARINE_MONITORING",geometry_json='{"type":"Polygon","coordinates":[]}',source="fixture",status="ACTIVE"))
    ts=[]
    for index in range(taxa):
        # Include a non-fish mollusc fixture to prove the projection is rank/taxon generic.
        name="Perna viridis" if index == 1 else f"Pterois fixture {index}"
        t=Species(scientific_name=name,common_name="Asian green mussel" if index == 1 else "Lionfish",taxonomic_rank="SPECIES",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier=str(1000+index),accepted_name_status="ACCEPTED",status="ACTIVE")
        db.add(t);db.flush();ts.append(t)
        db.add(RegionalTaxonRegistry(region_id=region.id,taxon_id=t.id,registry_version="fixture-v1",inclusion_basis="TEST_ONLY",source_references_json="[]",review_status="APPROVED",provenance_json="{}",provenance_fingerprint=f"fp-{index}"))
    db.commit();return region,js,ts

def make_dataset(**values):
    return ScientificDataset(source_name="fixture", source_type="TEST", source_reference="test://fixture", **values)


def test_matrix_preserves_multi_jurisdiction_and_multi_taxon_isolation():
    db=session();region,js,ts=seed(db)
    dataset=make_dataset(slug="j0-occ",name="J0 occurrence",dataset_type="OCCURRENCE",status="ACTIVE",species_id=ts[0].id,jurisdiction_id=js[0].id,geographic_scope_type="JURISDICTION",record_count=1)
    db.add(dataset);db.flush()
    db.add(GovernedOccurrenceEvidence(preparation_id=1,candidate_record_id=1,scientific_dataset_id=dataset.id,jurisdiction_id=js[0].id,taxon_id=ts[0].id,latitude=18,longitude=-77,boundary_id=1,evidence_fingerprint="occ-1",provenance_json="{}"));db.commit()
    result=RegionalScientificScalingService(db).matrix(region.id,page_size=20)
    assert result["total"] == 6
    by_key={(x["jurisdiction"]["id"],x["taxon"]["id"]):x for x in result["items"]}
    assert by_key[(js[0].id,ts[0].id)]["dimensions"]["occurrence"]["state"] == "READY"
    assert by_key[(js[1].id,ts[0].id)]["dimensions"]["occurrence"]["state"] == "BLOCKED"
    assert by_key[(js[0].id,ts[1].id)]["dimensions"]["occurrence"]["state"] == "BLOCKED"
    assert by_key[(js[0].id,ts[0].id)]["dimensions"]["ecology"]["state"] == "BLOCKED"


def test_approved_ecology_does_not_copy_and_conflict_is_preserved():
    db=session();region,js,ts=seed(db)
    user=User(email="admin@test.invalid",display_name="Admin",password_hash="x",is_platform_admin=True);db.add(user);db.flush()
    prep=EcologicalStatusPreparation(jurisdiction_id=js[0].id,source_organization="Fixture agency",source_title="Fixture list",source_reference="test://list",evidence_type="AUTHORITATIVE_LIST",authority_classification="AUTHORITATIVE_FOR_JURISDICTION",geographic_scope_json="{}",limitations_json="[]",manifest_json="{}",dependency_fingerprint="prep-1",workflow_status="APPLIED",prepared_by_user_id=user.id)
    db.add(prep);db.flush();candidate=EcologicalStatusCandidate(preparation_id=prep.id,submitted_scientific_name=ts[0].scientific_name,reconciled_taxon_id=ts[0].id,taxonomy_reconciliation="EXACT_GOVERNED_TAXON",asserted_statuses_json='["NATIVE","INVASIVE"]',preflight_classification="CONFLICT_WITH_EXISTING_STATUS",candidate_fingerprint="candidate-1",review_status="APPROVED",reviewer_user_id=user.id)
    db.add(candidate);db.flush()
    for status in ("NATIVE","INVASIVE"):
        db.add(EcologicalStatusAssertion(preparation_id=prep.id,candidate_id=candidate.id,jurisdiction_id=js[0].id,taxon_id=ts[0].id,asserted_status=status,source_organization="Fixture agency",source_title="Fixture list",source_reference="test://list",evidence_type="AUTHORITATIVE_LIST",authority_classification="AUTHORITATIVE_FOR_JURISDICTION",geographic_scope_json="{}",review_status="APPROVED",reviewer_user_id=user.id,review_reference="fixture",reviewed_at=datetime.now(timezone.utc),limitations_json="[]",provenance_json="{}",provenance_fingerprint=f"eco-{status}",lifecycle_state="CURRENT"))
    db.commit();service=RegionalScientificScalingService(db)
    first=service.detail(region.id,js[0].id,ts[0].id);second=service.detail(region.id,js[1].id,ts[0].id)
    assert first["conflict"] is True and first["dimensions"]["ecology"]["state"] == "REVIEW_REQUIRED"
    assert second["approved_statuses"] == [] and second["dimensions"]["ecology"]["state"] == "BLOCKED"
    comparison=service.taxon_comparison(region.id,ts[0].id)
    assert comparison["jurisdictions"][1]["state"] == "NO_GOVERNED_ECOLOGICAL_STATUS"


def test_preflight_is_read_only_and_explains_required_work():
    db=session();region,_,_=seed(db)
    protected=(Observation,GovernedOccurrenceEvidence,EcologicalStatusAssertion,SpeciesJurisdictionStatus,SpeciesProgram,SuitabilityDeployment,TrainingRun)
    before={m.__name__:db.query(m).count() for m in protected}
    result=RegionalScientificScalingService(db).preflight(region.id)
    assert result["count"] and "ECOLOGICAL_SOURCE_REQUIRED" in result["categories"]
    assert all(item["reason"] and item["next_workflow"] for item in result["items"])
    after={m.__name__:db.query(m).count() for m in protected}
    assert after == before


def test_dataset_applicability_is_role_and_jurisdiction_specific():
    db=session();region,js,ts=seed(db)
    dataset=make_dataset(slug="environment",name="Environmental fixture",dataset_type="ENVIRONMENTAL",status="ACTIVE",species_id=ts[0].id,geographic_scope_type="REGION",region_id=region.id,record_count=1)
    db.add(dataset);db.flush();db.add(ScientificDatasetApplicability(scientific_dataset_id=dataset.id,jurisdiction_id=js[0].id,evidence_role="ENVIRONMENTAL_COVARIATE",applicability_status="AUTHORIZED",reconciliation_method="REVIEW",reconciliation_version="v1",provenance_reference="test://review",provenance_json="{}",provenance_fingerprint="app-1"));db.commit()
    service=RegionalScientificScalingService(db)
    assert service.detail(region.id,js[0].id,ts[0].id)["dataset_applicability"]["ENVIRONMENTAL_COVARIATE"] == "READY"
    assert service.detail(region.id,js[1].id,ts[0].id)["dataset_applicability"]["ENVIRONMENTAL_COVARIATE"] == "BLOCKED"
    assert service.detail(region.id,js[0].id,ts[1].id)["dataset_applicability"]["ENVIRONMENTAL_COVARIATE"] == "BLOCKED"


def test_public_regional_catalog_language_and_empty_status_are_safe():
    db=session();region,_,taxa=seed(db)
    result=RegionalScientificScalingService(db).regional_taxa(region.id)
    assert result["total"] == 2 and "does not imply presence" in result["semantics"]
    assert result["items"][0]["approved_jurisdiction_statuses"] == []
    assert any(item["scientific_name"] == "Perna viridis" for item in result["items"])


def test_4000_combination_projection_is_batched_and_paginated():
    db=session();region,_,_=seed(db,jurisdictions=40,taxa=100)
    statements=0
    @event.listens_for(db.get_bind(),"before_cursor_execute")
    def count_queries(*_args):
        nonlocal statements;statements+=1
    started=time.perf_counter();result=RegionalScientificScalingService(db).matrix(region.id,page=1,page_size=50);elapsed=time.perf_counter()-started
    assert result["total"] == 4000 and len(result["items"]) == 50
    assert statements < 25
    assert elapsed < 5
    assert len(json.dumps(result)) < 500_000


def test_admin_scaling_routes_require_platform_admin_not_jurisdiction_reviewer():
    from api import app
    paths = {route.path: route for route in app.routes if hasattr(route, "dependant")}
    route = paths["/admin/regions/{region_id}/scientific-scaling/matrix"]
    dependencies = {dependency.call.__name__ for dependency in route.dependant.dependencies}
    assert "require_platform_admin" in dependencies
    assert "require_operational_reviewer" not in dependencies


def test_public_projection_omits_internal_and_private_fields():
    db=session();region,_,_=seed(db)
    payload=RegionalScientificScalingService(db).regional_taxa(region.id)
    serialized=json.dumps(payload).casefold()
    for forbidden in ("artifact_path", "local_path", "administrator", "reviewer_user", "reporter", "response_token", "provenance_fingerprint"):
        assert forbidden not in serialized
