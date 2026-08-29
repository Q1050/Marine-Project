from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base,get_db
from api import app
import api
from auth_service import create_session
from models import EcologicalStatusAssertion,GovernedOccurrenceEvidence,ObservationOperationalCase,ObservationOperationalEvent,ObservationReviewerGrant,ReporterAdditionalInformation,ScientificDatasetApplicability,SpeciesProgram,SuitabilityDeployment,TrainingRun,User
from observation_operations_service import ObservationOperationsService
from pilot_readiness_service import ReporterAccessService
from test_phase12f2_reviewer_authorization import fixture

def test_two_authenticated_http_sessions_claim_once(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'race.db'}",connect_args={"check_same_thread":False});Base.metadata.create_all(engine);Session=sessionmaker(bind=engine)
    seed=Session();jm,_,admin,first,obs=fixture(seed);second=User(email="second@test.invalid",display_name="Second reviewer",password_hash="x",status="ACTIVE",is_platform_admin=False);seed.add(second);seed.flush();seed.add(ObservationReviewerGrant(user_id=second.id,jurisdiction_id=jm.id,role="JURISDICTION_REVIEWER",status="ACTIVE",granted_by_user_id=admin.id,grant_reference="race"));seed.commit();first_token=create_session(seed,first);second_token=create_session(seed,second);observation_id=obs.id;reviewer_ids={first.id,second.id};seed.close()
    def override():
        db=Session()
        try:yield db
        finally:db.close()
    app.dependency_overrides[get_db]=override;client=TestClient(app)
    def claim(token):return client.post(f"/admin/observations/{observation_id}/claim",headers={"Authorization":f"Bearer {token}"},json={"reason":"Concurrent claim"})
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(claim,[first_token,second_token]))
        assert sorted(response.status_code for response in responses)==[200,409]
        check=Session();case=check.query(ObservationOperationalCase).filter_by(observation_id=observation_id).one();assert case.assigned_reviewer_user_id in reviewer_ids;assert check.query(ObservationOperationalEvent).filter_by(observation_id=observation_id,event_type="ASSIGNED").count()==1;check.close()
    finally:app.dependency_overrides.clear()

def test_phase10c_fixture_no_longer_requires_global_jurisdiction_cardinality():
    source=Path("test_phase10c_scientific_provenance.py").read_text(encoding="utf-8");assert "jurisdiction_datasets" in source;assert "geographic_scope_type == 'JURISDICTION').one()" not in source

def test_private_media_requires_active_matching_jurisdiction(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'media.db'}",connect_args={"check_same_thread":False});Base.metadata.create_all(engine);Session=sessionmaker(bind=engine);seed=Session();jm,bs,admin,reviewer,obs=fixture(seed);wrong=User(email="wrong@test.invalid",display_name="Wrong jurisdiction",password_hash="x",status="ACTIVE",is_platform_admin=False);seed.add(wrong);seed.flush();seed.add(ObservationReviewerGrant(user_id=wrong.id,jurisdiction_id=bs.id,role="JURISDICTION_REVIEWER",status="ACTIVE",granted_by_user_id=admin.id,grant_reference="privacy"));seed.commit();good_token=create_session(seed,reviewer);wrong_token=create_session(seed,wrong);observation_id=obs.id;grant_id=seed.query(ObservationReviewerGrant).filter_by(user_id=reviewer.id,jurisdiction_id=jm.id).one().id;seed.close();uploads=tmp_path/"uploads";uploads.mkdir();(uploads/"private.jpg").write_bytes(b"private-image");original=api.UPLOAD_DIRECTORY;api.UPLOAD_DIRECTORY=uploads
    def override():
        db=Session()
        try:yield db
        finally:db.close()
    app.dependency_overrides[get_db]=override;client=TestClient(app)
    try:
        assert client.get(f"/admin/observations/{observation_id}/image").status_code==401
        assert client.get(f"/admin/observations/{observation_id}/image",headers={"Authorization":f"Bearer {wrong_token}"}).status_code==403
        assert client.get(f"/admin/observations/{observation_id}/image",headers={"Authorization":f"Bearer {good_token}"}).content==b"private-image"
        revoke=Session();grant=revoke.get(ObservationReviewerGrant,grant_id);grant.status="REVOKED";revoke.commit();revoke.close();assert client.get(f"/admin/observations/{observation_id}/image",headers={"Authorization":f"Bearer {good_token}"}).status_code==403
        assert client.get("/uploads/observations/private.jpg").status_code==404
    finally:app.dependency_overrides.clear();api.UPLOAD_DIRECTORY=original

def test_disposable_jamaica_pilot_rehearsal_preserves_scientific_firewall():
    db=sessionmaker(bind=create_engine("sqlite:///:memory:"))();Base.metadata.create_all(db.bind);jm,_,_,reviewer,obs=fixture(db);service=ObservationOperationsService(db);before=(db.query(GovernedOccurrenceEvidence).count(),db.query(EcologicalStatusAssertion).count(),db.query(ScientificDatasetApplicability).count(),db.query(SpeciesProgram).count(),db.query(SuitabilityDeployment).count(),db.query(TrainingRun).count())
    service.claim(obs.id,reviewer.id,"Pilot claim");request=service.request_information(obs.id,reviewer.id,"Please provide the sighting context");ReporterAccessService(db).respond(request["reporter_response_token"],"Seen beside the pier at midday")
    assert db.query(ReporterAdditionalInformation).count()==1
    service.disposition(obs.id,"CONFIRMED",reviewer.id,reason="Expert-reviewed pilot fixture");result=service.close(obs.id,reviewer.id,"Pilot review complete");assert result["workflow_state"]=="CLOSED";assert result["evidence_handoff_state"]=="ELIGIBLE_FOR_SCIENTIFIC_EVIDENCE_REVIEW"
    events=[row.event_type for row in db.query(ObservationOperationalEvent).order_by(ObservationOperationalEvent.id)];assert events==["CASE_OPENED","ASSIGNED","ADDITIONAL_INFORMATION_REQUESTED","REPORTER_INFORMATION_RECEIVED","EXPERT_DISPOSITION","CLOSED"]
    after=(db.query(GovernedOccurrenceEvidence).count(),db.query(EcologicalStatusAssertion).count(),db.query(ScientificDatasetApplicability).count(),db.query(SpeciesProgram).count(),db.query(SuitabilityDeployment).count(),db.query(TrainingRun).count());assert after==before
