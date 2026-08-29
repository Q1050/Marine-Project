"""Controlled SQLite -> PostgreSQL migration and deterministic verification."""
from __future__ import annotations
from datetime import date,datetime,timezone
from pathlib import Path
import hashlib,json
from sqlalchemy import Integer,MetaData,Table,create_engine,func,inspect,select,text
from sqlalchemy.engine import Engine,make_url
from database import Base
import models  # register all ORM tables

TOOL_VERSION="sqlite-postgres-migration-v1"
CRITICAL_TABLES={"jurisdictions","jurisdiction_boundaries","species","regional_taxon_registry","scientific_datasets","scientific_dataset_applicabilities","historical_occurrences","governed_occurrence_evidence","ecological_status_assertions","observations","suitability_deployments","habitat_suitability_v3_grid_cells","anomaly_configurations","anomaly_assessments","observation_operational_events","scientific_domain_events","platform_audit_events"}

def safe_database_identity(url:str)->str:
    value=make_url(url);return f"{value.get_backend_name()}://{value.host or 'local'}:{value.port or 5432}/{value.database or ''}"

def validate_urls(source_url:str,target_url:str):
    source=make_url(source_url);target=make_url(target_url)
    if source.get_backend_name()!="sqlite":raise ValueError("Source must be SQLite")
    if target.get_backend_name()!="postgresql" or target.drivername!="postgresql+psycopg":raise ValueError("Target must use postgresql+psycopg")
    if not source.database or source.database==":memory:":raise ValueError("Source must be a persistent SQLite database")
    if not Path(source.database).is_file():raise ValueError("SQLite source does not exist")

def _value(value):
    if isinstance(value,datetime):
        # Legacy columns are TIMESTAMP WITHOUT TIME ZONE. Aware SQLite values
        # are normalized to the same UTC wall-clock instant for cross-backend
        # verification; no occurrence/event date is shifted.
        if value.tzinfo is not None:value=value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat()
    if isinstance(value,date):return value.isoformat()
    if isinstance(value,bytes):return value.hex()
    return value

def table_fingerprint(connection,table:Table):
    keys=[c.name for c in table.primary_key.columns] or [c.name for c in table.columns]
    rows=connection.execute(select(table).order_by(*[table.c[k] for k in keys])).mappings()
    digest=hashlib.sha256();count=0
    for row in rows:
        payload={k:_value(row[k]) for k in sorted(row)};digest.update(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode());digest.update(b"\n");count+=1
    return count,digest.hexdigest()

def _source_metadata(engine:Engine):
    metadata=MetaData();metadata.reflect(bind=engine);return metadata

def _ordered_names(source_meta:MetaData):
    names=set(source_meta.tables);dependencies={name:set() for name in names}
    for name,table in source_meta.tables.items():
        for fk in table.foreign_keys:
            referred=fk.column.table.name
            if referred==name:continue
            if name=="occurrence_candidate_records" and referred=="governed_occurrence_evidence":continue
            if referred in names:dependencies[name].add(referred)
    ordered=[];remaining=set(names)
    while remaining:
        ready=sorted(name for name in remaining if not (dependencies[name]&remaining))
        if not ready:raise ValueError("Unresolved foreign-key dependency cycle: "+", ".join(sorted(remaining)))
        ordered.extend(ready);remaining.difference_update(ready)
    return ordered

def _ensure_empty_target(target:Engine):
    names=inspect(target).get_table_names()
    with target.connect() as connection:
        populated=[name for name in names if connection.execute(text(f'SELECT 1 FROM "{name}" LIMIT 1')).first()]
    if populated:raise ValueError("Target contains data; migration refused: "+", ".join(sorted(populated)))

def _initialize_target(target:Engine):
    Base.metadata.create_all(target)
    with target.begin() as c:c.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(128) PRIMARY KEY, checksum VARCHAR(64) NOT NULL, applied_at TIMESTAMP NOT NULL)"))

def _target_tables(target:Engine,names):
    metadata=MetaData();metadata.reflect(bind=target,only=names);return metadata

def _reset_sequences(target:Engine,tables:MetaData):
    results=[]
    with target.begin() as c:
        for table in sorted(tables.tables.values(),key=lambda item:item.name):
            for column in table.primary_key.columns:
                if not isinstance(column.type,Integer):continue
                sequence=c.execute(text("SELECT pg_get_serial_sequence(:table_name,:column_name)"),{"table_name":table.name,"column_name":column.name}).scalar()
                if not sequence:continue
                maximum=c.execute(select(func.max(column))).scalar()
                if maximum is None:c.execute(text("SELECT setval(:sequence,1,false)"),{"sequence":sequence})
                else:c.execute(text("SELECT setval(:sequence,:maximum,true)"),{"sequence":sequence,"maximum":maximum})
                results.append({"table":table.name,"column":column.name,"maximum":maximum,"sequence":sequence.split(".")[-1]})
    return results

def migrate_sqlite_to_postgres(source_url:str,target_url:str,dry_run=False,manifest_path:Path|None=None):
    validate_urls(source_url,target_url);started=datetime.now(timezone.utc);source=create_engine(source_url);target=create_engine(target_url,pool_pre_ping=True)
    source_meta=_source_metadata(source);names=_ordered_names(source_meta);source_path=Path(make_url(source_url).database)
    manifest={"tool_version":TOOL_VERSION,"source_sha256":hashlib.sha256(source_path.read_bytes()).hexdigest(),"target":safe_database_identity(target_url),"started_at":started.isoformat(),"dry_run":dry_run,"tables":{},"sequence_resets":[],"integrity":"PENDING"}
    with source.connect() as c:
        for name in names:
            count,fp=table_fingerprint(c,source_meta.tables[name]);manifest["tables"][name]={"source_count":count,"source_fingerprint":fp}
    if dry_run:
        manifest["integrity"]="DRY_RUN_COMPLETE";return manifest
    _ensure_empty_target(target);_initialize_target(target);target_meta=_target_tables(target,names)
    missing=set(names)-set(target_meta.tables)
    if missing:raise ValueError("Target schema is missing tables: "+", ".join(sorted(missing)))
    deferred_updates=[]
    with source.connect() as src,target.begin() as dst:
        for name in names:
            source_table=source_meta.tables[name];target_table=target_meta.tables[name]
            source_columns={c.name for c in source_table.columns};target_columns={c.name for c in target_table.columns}
            if source_columns-target_columns:raise ValueError(f"Target table {name} lacks columns: {sorted(source_columns-target_columns)}")
            batch=[]
            for row in src.execute(select(source_table)).mappings():
                values={key:row[key] for key in source_columns}
                # This reviewed linkage is intentionally bidirectional. Insert
                # candidates first with the nullable reverse link, then repair
                # it after governed evidence exists.
                if name=="occurrence_candidate_records" and values.get("applied_evidence_id") is not None:
                    deferred_updates.append((values["id"],values["applied_evidence_id"]));values["applied_evidence_id"]=None
                batch.append(values)
                if len(batch)>=500:dst.execute(target_table.insert(),batch);batch=[]
            if batch:dst.execute(target_table.insert(),batch)
        if deferred_updates:
            candidates=target_meta.tables["occurrence_candidate_records"]
            for candidate_id,evidence_id in deferred_updates:dst.execute(candidates.update().where(candidates.c.id==candidate_id).values(applied_evidence_id=evidence_id))
    manifest["sequence_resets"]=_reset_sequences(target,target_meta)
    with target.connect() as dst:
        for name in names:
            count,fp=table_fingerprint(dst,target_meta.tables[name]);entry=manifest["tables"][name];entry.update(target_count=count,target_fingerprint=fp,status="MATCH" if count==entry["source_count"] and fp==entry["source_fingerprint"] else "MISMATCH")
        invalid=dst.execute(text("SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated")).scalar()
    mismatches=[name for name,value in manifest["tables"].items() if value["status"]!="MATCH"]
    manifest["foreign_keys"]={"unvalidated_constraints":invalid,"status":"PASS" if invalid==0 else "FAIL"};manifest["integrity"]="PASS" if not mismatches and invalid==0 else "FAIL";manifest["completed_at"]=datetime.now(timezone.utc).isoformat();manifest["critical_tables_verified"]=sorted(CRITICAL_TABLES&set(names))
    if manifest_path:manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True),encoding="utf-8")
    if manifest["integrity"]!="PASS":raise RuntimeError("Migration verification failed: "+", ".join(mismatches))
    return manifest
