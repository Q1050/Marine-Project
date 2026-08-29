"""Additive/idempotent Phase 12A-5 onboarding governance migration."""
import json, sqlite3
from datetime import datetime, timezone


def _columns(c,t): return {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
def _exists(c,t): return c.execute("select 1 from sqlite_master where type='table' and name=?",(t,)).fetchone() is not None


def run_migration(c: sqlite3.Connection):
    summary={"sovereign_parent_added":False,"artifact_table_created":False,"onboarding_table_created":False,"barbados_record_backfilled":0}
    with c:
        if "sovereign_parent_id" not in _columns(c,"jurisdictions"):
            c.execute("ALTER TABLE jurisdictions ADD COLUMN sovereign_parent_id INTEGER REFERENCES jurisdictions(id) ON DELETE RESTRICT")
            c.execute("CREATE INDEX ix_jurisdictions_sovereign_parent_id ON jurisdictions(sovereign_parent_id)"); summary["sovereign_parent_added"]=True
        before=_exists(c,"artifact_references")
        c.execute("""CREATE TABLE IF NOT EXISTS artifact_references(id INTEGER PRIMARY KEY,local_path VARCHAR(512),external_uri VARCHAR(1024),sha256 VARCHAR(64) NOT NULL UNIQUE,media_type VARCHAR(128) NOT NULL,artifact_type VARCHAR(64) NOT NULL,size_bytes INTEGER NOT NULL,provider VARCHAR(256),source_reference VARCHAR(1024),availability_status VARCHAR(32) NOT NULL DEFAULT 'AVAILABLE',created_at DATETIME NOT NULL)""")
        summary["artifact_table_created"]=not before
        before=_exists(c,"jurisdiction_onboarding_records")
        c.execute("""CREATE TABLE IF NOT EXISTS jurisdiction_onboarding_records(id INTEGER PRIMARY KEY,jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id) ON DELETE RESTRICT,manifest_version VARCHAR(128) NOT NULL,manifest_fingerprint VARCHAR(64) NOT NULL,canonical_identifier_scheme VARCHAR(32) NOT NULL,canonical_identifier VARCHAR(64) NOT NULL,boundary_id INTEGER NOT NULL REFERENCES jurisdiction_boundaries(id) ON DELETE RESTRICT,source_artifact_reference_id INTEGER REFERENCES artifact_references(id) ON DELETE RESTRICT,boundary_source_sha256 VARCHAR(64) NOT NULL,geometry_sha256 VARCHAR(64) NOT NULL,action_performed VARCHAR(32) NOT NULL,execution_mode VARCHAR(16) NOT NULL,approval_state VARCHAR(64) NOT NULL,applied_at DATETIME,operator_reference VARCHAR(256),before_state_json TEXT NOT NULL,after_state_json TEXT NOT NULL,created_at DATETIME NOT NULL,UNIQUE(manifest_fingerprint,execution_mode))""")
        summary["onboarding_table_created"]=not before
        now=datetime.now(timezone.utc).isoformat()
        c.execute("INSERT OR IGNORE INTO artifact_references(local_path,external_uri,sha256,media_type,artifact_type,size_bytes,provider,source_reference,availability_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",("data/jurisdiction_boundaries/marine-regions-v12-barbados-wfs-source.geojson",None,"5b42df93f1163857566e070c7df24340d8475663bd72f3748771ce019600e947","application/geo+json","JURISDICTION_BOUNDARY_SOURCE",48701,"Marine Regions / VLIZ","https://doi.org/10.14284/632","AVAILABLE",now))
        barbados=c.execute("select id from jurisdictions where canonical_identifier='BB'").fetchone(); boundary=c.execute("select id,activated_at from jurisdiction_boundaries where jurisdiction_id=? and status='ACTIVE'",(barbados[0],)).fetchone() if barbados else None
        artifact=c.execute("select id from artifact_references where sha256=?",("5b42df93f1163857566e070c7df24340d8475663bd72f3748771ce019600e947",)).fetchone()
        if barbados and boundary:
            cursor=c.execute("""INSERT OR IGNORE INTO jurisdiction_onboarding_records(jurisdiction_id,manifest_version,manifest_fingerprint,canonical_identifier_scheme,canonical_identifier,boundary_id,source_artifact_reference_id,boundary_source_sha256,geometry_sha256,action_performed,execution_mode,approval_state,applied_at,operator_reference,before_state_json,after_state_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(barbados[0],"barbados-onboarding-manifest-v1","f536e77d272204bf9e7175817c9207ecd96f4813b0ee56cc8fa30e64f36ba14a","ISO_3166_1_ALPHA_2","BB",boundary[0],artifact[0],"5b42df93f1163857566e070c7df24340d8475663bd72f3748771ce019600e947","1ee8e235f559e5c907e7957b3b60dfcd6e6ad9adc72aedcbac6d879fe7849226","CREATE","APPLY","APPROVED_FOR_CONTROLLED_PHASE_12A_4_APPLY",boundary[1],"PHASE_12A_4_CONTROLLED_APPLY",json.dumps({"boundaries":2,"jurisdictions":2},sort_keys=True,separators=(",",":")),json.dumps({"boundaries":3,"jurisdictions":3},sort_keys=True,separators=(",",":")),now)); summary["barbados_record_backfilled"]=cursor.rowcount
        for table,column in (("artifact_references","artifact_type"),("jurisdiction_onboarding_records","jurisdiction_id"),("jurisdiction_onboarding_records","manifest_fingerprint")):
            c.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table}({column})")
    return summary
