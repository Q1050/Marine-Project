from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from early_warning_operations import EarlyWarningOperations
from early_warning_service import EarlyWarningService
from milestone13d_closure_migrate import run_migration
from models import GovernedOccurrenceEvidence, HabitatSuitabilityModel, ScientificDomainEvent, SpeciesProgram, SuitabilityDeployment, AnomalyReviewAssignment
from suitability_deployment_governance import SuitabilityDeploymentGovernance
from test_milestone13c_early_warning import observation, seed


def temporal_configuration(session, jurisdiction, taxon, days=30, minimum=1):
    values={"jurisdiction_id":jurisdiction.id,"taxon_id":taxon.id,"configuration_version":f"temporal-{days}-{minimum}","enabled_signal_types_json":'["TEMPORAL_CONTEXT"]',"spatial_rule_json":None,"temporal_rule_json":f'{{"rule_id":"synthetic-temporal","rule_version":"test-v1","minimum_days_since_latest_record":{days},"minimum_dated_records":{minimum}}}',"mode":"RULE_BASED","environmental_context_json":"{}","minimum_evidence_json":"{}","algorithm_version":"marine-early-warning-v1","provenance_json":'{"fixture":true}',"limitations_json":'["Synthetic test rule only"]'}
    operations=EarlyWarningOperations(session);row=operations.config_draft(values);operations.transition_config(row,"READY_FOR_REVIEW");operations.transition_config(row,"APPROVED",1,"test-only");operations.transition_config(row,"ACTIVE");return row


def add_baseline(session,jurisdiction,taxon,age_days=100,candidate=1):
    row=GovernedOccurrenceEvidence(preparation_id=1,candidate_record_id=candidate,scientific_dataset_id=1,jurisdiction_id=jurisdiction.id,taxon_id=taxon.id,latitude=1,longitude=1,event_date=datetime.now(timezone.utc)-timedelta(days=age_days),boundary_id=1,evidence_fingerprint=f"temporal-{candidate}",provenance_json="{}")
    session.add(row);session.flush();return row


def test_reviewed_temporal_rule_triggers_and_explains_version():
    session,jurisdiction,taxon=seed();add_baseline(session,jurisdiction,taxon,100);observed=observation(session,jurisdiction,taxon);temporal_configuration(session,jurisdiction,taxon,30)
    assessment=EarlyWarningService(session).evaluate(observed.id);payload=EarlyWarningService(session).payload(assessment)
    assert assessment.overall_status=="REVIEW_SUGGESTED" and "temporal-30-1" in payload["explanation"]
    temporal=next(x for x in payload["signals"] if x["signal_type"]=="TEMPORAL_CONTEXT");assert temporal["evidence"]["review_trigger"] is True


def test_temporal_not_satisfied_and_insufficient_are_conservative():
    session,jurisdiction,taxon=seed();add_baseline(session,jurisdiction,taxon,5);observed=observation(session,jurisdiction,taxon);temporal_configuration(session,jurisdiction,taxon,30)
    assessment=EarlyWarningService(session).evaluate(observed.id);assert assessment.overall_status=="NO_REVIEW_SIGNAL"
    session2,j2,t2=seed();add_baseline(session2,j2,t2,100);observed2=observation(session2,j2,t2);temporal_configuration(session2,j2,t2,30,2)
    payload=EarlyWarningService(session2).payload(EarlyWarningService(session2).evaluate(observed2.id));temporal=next(x for x in payload["signals"] if x["signal_type"]=="TEMPORAL_CONTEXT");assert temporal["evidence"]["categorical_result"]=="INSUFFICIENT_TEMPORAL_COVERAGE" and not temporal["evidence"]["review_trigger"]


def test_descriptive_mode_refuses_trigger_rules():
    session,jurisdiction,taxon=seed();values={"jurisdiction_id":jurisdiction.id,"taxon_id":taxon.id,"configuration_version":"bad","enabled_signal_types_json":"[]","spatial_rule_json":None,"temporal_rule_json":'{"rule_id":"x","rule_version":"1"}',"mode":"DESCRIPTIVE_ONLY","environmental_context_json":"{}","minimum_evidence_json":"{}","provenance_json":"{}","limitations_json":'["x"]'}
    with pytest.raises(ValueError):EarlyWarningOperations(session).config_draft(values)


def test_configuration_activation_event_is_idempotent():
    session,jurisdiction,taxon=seed();row=temporal_configuration(session,jurisdiction,taxon)
    events=session.query(ScientificDomainEvent).filter_by(event_type="ANOMALY_CONFIGURATION_CHANGED").all();assert len(events)==1 and str(row.id) in events[0].dependency_reference


def test_scientific_deployment_activation_replacement_and_public_display_firewall():
    session,jurisdiction,taxon=seed();program=SpeciesProgram(jurisdiction_id=jurisdiction.id,species_id=taxon.id,scientific_name=taxon.scientific_name,status="ACTIVE");session.add(program);session.flush();model=HabitatSuitabilityModel(model_version="fixture-model",scientific_name=taxon.scientific_name,algorithm="fixture",feature_list_json="[]",training_generation_version="fixture",training_sample_count=1,eligible_presence_count=1,eligible_background_count=0,spatial_block_count=1,validation_metrics_json="{}",coefficients_json="{}",artifact_path="fixture");session.add(model);session.flush();first=SuitabilityDeployment(species_program_id=program.id,habitat_suitability_model_id=model.id,model_version="fixture-v1",status="ACTIVE",artifact_hash="a");second=SuitabilityDeployment(species_program_id=program.id,habitat_suitability_model_id=model.id,model_version="fixture-v2",status="CANDIDATE",artifact_hash="b");session.add_all([first,second]);session.flush()
    row,changed=SuitabilityDeploymentGovernance(session).activate(second.id,"test replacement");assert changed and row.status=="ACTIVE" and first.status=="SUPERSEDED";assert session.query(ScientificDomainEvent).filter_by(event_type="SUITABILITY_DEPLOYMENT_CHANGED").count()==1
    second.public_display_status="PUBLIC_APPROVED";session.flush();assert session.query(ScientificDomainEvent).filter_by(event_type="SUITABILITY_DEPLOYMENT_CHANGED").count()==1


def test_partial_unique_index_enforces_one_active_assignment(tmp_path):
    path=tmp_path/"claims.db"
    with sqlite3.connect(path) as connection:
        first=run_migration(connection);second=run_migration(connection);assert first["active_assignment_unique_index_created"] and not second["active_assignment_unique_index_created"]
        connection.execute("insert into anomaly_review_assignments(id,anomaly_assessment_id,jurisdiction_id,reviewer_user_id,status,assigned_by_user_id,assigned_at,reason) values(1,1,1,1,'ASSIGNED',1,CURRENT_TIMESTAMP,'first')")
        with pytest.raises(sqlite3.IntegrityError):connection.execute("insert into anomaly_review_assignments(id,anomaly_assessment_id,jurisdiction_id,reviewer_user_id,status,assigned_by_user_id,assigned_at,reason) values(2,1,1,2,'ASSIGNED',2,CURRENT_TIMESTAMP,'race')")
        connection.execute("update anomaly_review_assignments set status='UNASSIGNED' where id=1");connection.execute("insert into anomaly_review_assignments(id,anomaly_assessment_id,jurisdiction_id,reviewer_user_id,status,assigned_by_user_id,assigned_at,reason) values(2,1,1,2,'ASSIGNED',2,CURRENT_TIMESTAMP,'reassign')")
