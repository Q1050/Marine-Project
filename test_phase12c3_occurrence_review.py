import sqlite3
from datetime import datetime,timezone
from pathlib import Path
import pytest
from models import *
from occurrence_candidate_review import OccurrenceCandidateReviewService
from occurrence_evidence_service import OccurrenceEvidenceService,OccurrenceSourceRegistry
from jurisdiction_taxon_readiness import JurisdictionTaxonReadinessService
from phase12c3_migrate_occurrence_reviews import run_migration
from test_phase12c1_occurrence_evidence import FixtureSource,context,record

def service_for(context,records):
 session,root,*_=context;return OccurrenceEvidenceService(session,OccurrenceSourceRegistry([FixtureSource(root,records)]))

def test_dispositions_eligibility_overlap_links_partial_apply_and_firewall(context):
 session,_,admin,region,jamaica,barbados,taxon,_=context
 bahamas=Jurisdiction(region_id=region.id,name="Bahamas",slug="bahamas",country_code="BS",status="ACTIVE",center_latitude=25,center_longitude=-77,default_zoom=7);session.add(bahamas)
 legacy=HistoricalOccurrence(scientific_name=taxon.scientific_name,taxon_id=159559,latitude=18,longitude=-77,event_date=datetime(2020,1,2),occurrence_id="legacy",source="OBIS",deduplication_key="legacy",imported_at=datetime.now(timezone.utc));session.add(legacy);session.commit()
 records=[record("new",lat=18.2),record("legacy"),record("outside",lat=25),record("unlicensed",lat=18.3,source_metadata={"scientific_provider":"UWI","provider_identity_status":"REPORTED","transport_interface":"OBIS","license":None})]
 svc=service_for(context,records);prepared=svc.prepare(jamaica.id,taxon.id,"ECOREEF",admin.id);review=OccurrenceCandidateReviewService(session);report=review.initialize(prepared["id"],admin.id)
 assert report["counts"]=={"REVIEW_REQUIRED":2,"KNOWN_LEGACY_OVERLAP":1,"REJECTED_OUTSIDE_JURISDICTION":1};assert report["legacy_links"]==1
 candidates={row.provider_occurrence_id:row for row in session.query(OccurrenceCandidateRecord).filter_by(preparation_id=prepared["id"])}
 with pytest.raises(ValueError,match="not eligible"):review.review(prepared["id"],[candidates["outside"].id],"APPROVED_AS_NEW_EVIDENCE",admin.id,"review")
 with pytest.raises(ValueError,match="RECORD_LICENSE_UNRESOLVED"):review.review(prepared["id"],[candidates["unlicensed"].id],"APPROVED_AS_NEW_EVIDENCE",admin.id,"review")
 review.review(prepared["id"],[candidates["new"].id],"APPROVED_AS_NEW_EVIDENCE",admin.id,"review","Provider, license, identity, taxonomy, boundary, and duplication reviewed.")
 before={model:session.query(model).count() for model in (SpeciesJurisdictionStatus,SpeciesProgram,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal)}
 applied=svc.apply(prepared["id"]);assert applied["apply_status"]=="APPLIED" and applied["scientific_event_emitted"];assert session.query(ScientificDomainEvent).filter_by(event_type="GOVERNED_OCCURRENCE_BASELINE_CHANGED").count()==1;assert svc.apply(prepared["id"])["apply_status"]=="NO-OP";assert session.query(ScientificDomainEvent).filter_by(event_type="GOVERNED_OCCURRENCE_BASELINE_CHANGED").count()==1
 assert session.query(GovernedOccurrenceEvidence).count()==1 and session.query(ScientificDataset).filter_by(jurisdiction_id=jamaica.id).count()==1
 applicability=session.query(ScientificDatasetApplicability).filter_by(jurisdiction_id=jamaica.id).one();assert applicability.evidence_role=="OCCURRENCE_HISTORY"
 assert before=={model:session.query(model).count() for model in before};assert session.query(GovernedOccurrenceEvidence).filter(GovernedOccurrenceEvidence.jurisdiction_id.in_([barbados.id,bahamas.id])).count()==0
 assert JurisdictionTaxonReadinessService(session).evaluate(jamaica,taxon).as_dict()["dimensions"]["occurrence_evidence"]["state"]=="READY"
 assert JurisdictionTaxonReadinessService(session).evaluate(barbados,taxon).as_dict()["dimensions"]["occurrence_evidence"]["state"]=="BLOCKED"
 assert JurisdictionTaxonReadinessService(session).evaluate(bahamas,taxon).as_dict()["dimensions"]["occurrence_evidence"]["state"]=="BLOCKED"

def test_stale_review_refused_and_audit_is_immutable(context):
 session,_,admin,_,jamaica,_,taxon,_=context;svc=service_for(context,[record()]);prepared=svc.prepare(jamaica.id,taxon.id,"ECOREEF",admin.id);review=OccurrenceCandidateReviewService(session);review.initialize(prepared["id"],admin.id);row=session.get(OccurrenceAcquisitionPreparation,prepared["id"]);row.workflow_status="STALE";session.commit()
 with pytest.raises(ValueError,match="not reviewable"):review.review(row.id,[prepared["candidates"][0]["id"]],"APPROVED_AS_NEW_EVIDENCE",admin.id,"review")
 audit=session.query(OccurrenceCandidateReview).first();audit.reason_code="changed"
 with pytest.raises(ValueError,match="append-only"):session.commit()
 session.rollback()

def test_migration_is_additive_and_idempotent(tmp_path):
 connection=sqlite3.connect(tmp_path/"review.db");connection.executescript("CREATE TABLE occurrence_acquisition_preparations(id INTEGER PRIMARY KEY);CREATE TABLE occurrence_candidate_records(id INTEGER PRIMARY KEY);CREATE TABLE historical_occurrences(id INTEGER PRIMARY KEY);CREATE TABLE governed_occurrence_evidence(id INTEGER PRIMARY KEY);CREATE TABLE users(id INTEGER PRIMARY KEY);")
 assert run_migration(connection)=={"review_table_created":True,"legacy_link_table_created":True};assert run_migration(connection)=={"review_table_created":False,"legacy_link_table_created":False}

def test_admin_review_mutation_is_protected():
 from fastapi.testclient import TestClient
 from api import app
 assert TestClient(app).post("/admin/occurrence-evidence/preparations/3/initialize-review").status_code==401

def test_frontend_disables_scientifically_ineligible_approval():
 text=Path("marine-monitoring-frontend/src/components/admin/OccurrenceEvidencePanel.jsx").read_text(encoding="utf-8")
 assert "approvalSafe" in text and "disabled={!approvalSafe || busy}" in text and "candidate.eligibility?.eligible" in text
