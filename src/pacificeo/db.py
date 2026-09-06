from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from pacificeo.settings import get_settings


def build_engine():
    url = get_settings().database_url.get_secret_value()
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, pool_pre_ping=True, future=True)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def tenant_session(tenant_id: str, user_id: str | None = None) -> Iterator[Session]:
    """Open a transaction scoped to the tenant enforced by Postgres RLS."""
    with SessionLocal.begin() as session:
        session.execute(text("select set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
        if user_id:
            session.execute(text("select set_config('app.user_id', :user_id, true)"), {"user_id": user_id})
        yield session
