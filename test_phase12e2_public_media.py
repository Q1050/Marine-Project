import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import *
from public_media_service import PublicMediaService
from phase12e2_migrate_public_media import run_migration

def test_media_lifecycle_public_filter_primary_and_privacy():
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);s=sessionmaker(bind=engine)();user=User(email="a@b.c",display_name="A",password_hash="x",is_platform_admin=True);taxon=Species(scientific_name="Testus marinus",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="e"*64);s.add_all([user,taxon]);s.commit();service=PublicMediaService(s);row=service.create({"media_type":"TAXON_REFERENCE_IMAGE","taxon_id":taxon.id,"source_provider":"Museum","creator":"Creator","source_reference":"https://museum.test/item","license":"CC-BY-4.0","attribution_text":"Creator / Museum","remote_url":"https://images.test/species.jpg","provenance_json":"{}","limitations_json":"[]"});assert service.public_for_taxon(taxon.id)==[];service.review(row,user.id,"APPROVED");service.publish(row,True);safe=service.safe(row);assert safe["is_primary"] and safe["license"]=="CC-BY-4.0" and "Creator" in safe["attribution_text"] and "artifact" not in safe
 observation=Observation(image_filename="private.jpg",latitude=0,longitude=0,identification_status="UNKNOWN",ecological_status="UNKNOWN",decision="REVIEW",priority="LOW",verification_status="PENDING");s.add(observation);s.commit();assert service.public_for_taxon(taxon.id)==[row]

def test_migration_idempotent(tmp_path):
 path=tmp_path/"db.sqlite";c=sqlite3.connect(path);c.executescript("CREATE TABLE species(id INTEGER PRIMARY KEY);CREATE TABLE users(id INTEGER PRIMARY KEY);CREATE TABLE artifact_references(id INTEGER PRIMARY KEY);CREATE TABLE observations(id INTEGER PRIMARY KEY);");first=run_migration(c);second=run_migration(c);assert first["tables_created"]==["governed_public_media"] and len(first["columns_added"])==2 and second=={"tables_created":[],"columns_added":[]}

def test_frontend_contracts_are_scientifically_safe():
 text=open("marine-monitoring-frontend/src/pages/PublicDirectoryPages.jsx",encoding="utf-8").read();submit=open("marine-monitoring-frontend/src/pages/SubmitPage.jsx",encoding="utf-8").read();assert "does not confirm species presence" in text and "Environmental suitability" in text and "No approved public reference image" in text;assert "suggestion does not determine the final identification" in submit
