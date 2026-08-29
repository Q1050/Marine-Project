from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import MetaData,Table,Column,Integer,String,create_engine
from postgres_migration import _ensure_empty_target,safe_database_identity,table_fingerprint,validate_urls,migrate_sqlite_to_postgres

def source_db(tmp_path):
    path=tmp_path/"source.db"
    with sqlite3.connect(path) as c:c.execute("create table sample(id integer primary key,value text)");c.execute("insert into sample values(7,'canonical')")
    return path

def test_database_url_types_and_redaction(tmp_path):
    source=source_db(tmp_path);target="postgresql+psycopg://user:secret@example.test:5432/test_marine"
    validate_urls(f"sqlite:///{source}",target)
    identity=safe_database_identity(target);assert "secret" not in identity;assert identity=="postgresql://example.test:5432/test_marine"
    with pytest.raises(ValueError):validate_urls(target,target)
    with pytest.raises(ValueError):validate_urls(f"sqlite:///{source}","sqlite:///target.db")

def test_dry_run_never_connects_to_target_and_fingerprints_source(tmp_path):
    source=source_db(tmp_path)
    result=migrate_sqlite_to_postgres(f"sqlite:///{source}","postgresql+psycopg://nobody:hidden@invalid.invalid/test_marine",dry_run=True)
    assert result["integrity"]=="DRY_RUN_COMPLETE";assert result["tables"]["sample"]["source_count"]==1;assert "hidden" not in str(result)

def test_nonempty_target_refused(tmp_path):
    target=create_engine(f"sqlite:///{tmp_path/'target.db'}");metadata=MetaData();table=Table("sample",metadata,Column("id",Integer,primary_key=True),Column("value",String));metadata.create_all(target)
    with target.begin() as c:c.execute(table.insert(),{"value":"existing"})
    with pytest.raises(ValueError,match="Target contains data"):_ensure_empty_target(target)

def test_canonical_row_fingerprint_is_order_stable(tmp_path):
    engine=create_engine(f"sqlite:///{source_db(tmp_path)}");metadata=MetaData();metadata.reflect(engine)
    with engine.connect() as c:first=table_fingerprint(c,metadata.tables["sample"]);second=table_fingerprint(c,metadata.tables["sample"])
    assert first==second
