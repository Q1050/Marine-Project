from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from platform_config import settings

DATABASE_URL = settings.database_url
IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRESQL = DATABASE_URL.startswith("postgresql")
if not (IS_SQLITE or IS_POSTGRESQL):
    raise RuntimeError("DATABASE_URL must use sqlite or postgresql+psycopg")

engine_options = {"pool_pre_ping": True}
if IS_SQLITE:
    engine_options["connect_args"] = {"check_same_thread": False}
else:
    engine_options.update(pool_size=settings.database_pool_size,max_overflow=settings.database_max_overflow,pool_timeout=settings.database_pool_timeout_seconds)
engine = create_engine(DATABASE_URL, **engine_options)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
