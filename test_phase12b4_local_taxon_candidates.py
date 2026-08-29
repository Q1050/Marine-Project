import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import *
from regional_taxonomy_bulk_service import RegionalTaxonomyBulkService
from test_phase12b3_regional_taxonomy_bulk import FixtureProvider
from phase12b4_migrate_local_taxon_candidates import run_migration

def setup(tmp):
 e=create_engine("sqlite:///:memory:");Base.metadata.create_all(e);s=sessionmaker(bind=e)();r=Region(name="Pacific",slug="pacific",status="ACTIVE");s.add(r);s.flush();s.add(User(email="a@b.c",display_name="a",password_hash="x",is_platform_admin=True));p=Species(scientific_name="Pterois volitans",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="159559",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="a"*64);s.add(p);s.commit();return s,r

def test_new_candidate_prepare_approval_apply_and_firewall(tmp_path):
 s,r=setup(tmp_path);svc=RegionalTaxonomyBulkService(s,FixtureProvider(tmp_path));before_species=s.query(Species).count();before={m:s.query(m).count() for m in (SpeciesProgram,SpeciesJurisdictionStatus,ScientificDatasetApplicability,HistoricalOccurrence,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal)}
 dry=svc.plan(r.id,[{"submitted_scientific_name":"Pterois miles"}],True)[0];assert dry["status"]=="CREATE_LOCAL_TAXON_CANDIDATE" and s.query(LocalTaxonCandidate).count()==0 and s.query(Species).count()==before_species
 prepared=svc.plan(r.id,[{"submitted_scientific_name":"Pterois miles"}],False,"admin")[0];candidate=s.get(LocalTaxonCandidate,prepared["local_taxon_candidate_id"]);assert candidate.workflow_status=="READY_FOR_REVIEW" and s.query(Species).count()==before_species
 assert svc.approve_candidate_batch([candidate.id],1,"review")[0]["status"]=="APPROVED";result=svc.apply_candidate_batch([candidate.id])[0];assert result["status"]=="APPLIED" and s.query(Species).count()==before_species+1
 created=s.get(Species,result["species_id"]);assert created.authoritative_identifier=="159560" and created.provenance_fingerprint and s.query(RegionalTaxonRegistry).filter_by(region_id=r.id,taxon_id=created.id).count()==1
 assert before=={m:s.query(m).count() for m in before};assert svc.apply_candidate_batch([candidate.id])[0]["status"]=="NO-OP"

def test_duplicate_candidate_and_existing_species_race_reuse(tmp_path):
 s,r=setup(tmp_path);svc=RegionalTaxonomyBulkService(s,FixtureProvider(tmp_path));first=svc.plan(r.id,[{"submitted_scientific_name":"Pterois miles"}],False,"a")[0];second=svc.plan(r.id,[{"submitted_scientific_name":"Pterois miles"}],False,"b")[0];assert first["local_taxon_candidate_id"]==second["local_taxon_candidate_id"]
 candidate=s.get(LocalTaxonCandidate,first["local_taxon_candidate_id"]);svc.approve_candidate_batch([candidate.id],1,"r")
 appeared=Species(scientific_name="Pterois miles",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="159560",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="c"*64);s.add(appeared);s.commit();result=svc.apply_candidate_batch([candidate.id])[0];assert result["species_id"]==appeared.id and s.query(Species).filter_by(authoritative_identifier="159560").count()==1

def test_synonym_preserved_without_duplicate_accepted_entity(tmp_path):
 s,r=setup(tmp_path);svc=RegionalTaxonomyBulkService(s,FixtureProvider(tmp_path));prepared=svc.plan(r.id,[{"submitted_scientific_name":"Gasterosteus volitans"}],False,"a")[0];candidate=s.get(LocalTaxonCandidate,prepared["local_taxon_candidate_id"]);svc.approve_candidate_batch([candidate.id],1,"r");result=svc.apply_candidate_batch([candidate.id])[0];synonym=s.get(Species,result["species_id"]);accepted=s.query(Species).filter_by(authoritative_identifier="159559").one();assert synonym.accepted_name_status=="SYNONYM" and synonym.accepted_taxon_id==accepted.id and synonym.id!=accepted.id

def test_migration_idempotent(tmp_path):
 c=sqlite3.connect(tmp_path/"m.db");c.executescript("CREATE TABLE regions(id INTEGER PRIMARY KEY);CREATE TABLE users(id INTEGER PRIMARY KEY);CREATE TABLE species(id INTEGER PRIMARY KEY);CREATE TABLE regional_taxon_registry(id INTEGER PRIMARY KEY);");assert run_migration(c)["table_created"] and not run_migration(c)["table_created"]

def test_admin_candidate_endpoint_protected():
 from fastapi.testclient import TestClient
 from api import app
 assert TestClient(app).get("/admin/taxonomy/local-candidates/1").status_code==401
