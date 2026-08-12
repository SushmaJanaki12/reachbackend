from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(engine, "connect")
def _set_session_timezone_utc(dbapi_connection, connection_record):
    # Plain SET (session-level, as opposed to SET LOCAL) is still rolled
    # back if the transaction it was issued in gets rolled back -- and every
    # DBAPI connection starts inside an implicit transaction. Without this
    # commit, the very first rollback on a freshly pooled connection (e.g.
    # any read-only request whose session never calls .commit(), since
    # Session.close() rolls back a still-open transaction) silently reverts
    # this connection's timezone to the Postgres role/server default for
    # the rest of its life in the pool -- here, Asia/Kolkata, not UTC. That
    # desyncs stored naive-UTC timestamps (Message.sent_at etc.) from
    # datetime.now(timezone.utc) comparisons elsewhere in the app.
    cursor = dbapi_connection.cursor()
    cursor.execute("SET TIME ZONE 'UTC'")
    cursor.close()
    dbapi_connection.commit()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
