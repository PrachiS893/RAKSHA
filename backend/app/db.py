"""Database engine and session management for Raksha backend."""

from collections.abc import Generator
from sqlmodel import Session, SQLModel, create_engine
import app.models  # noqa: F401 - Register all models with SQLModel metadata
from app.config import settings

# SQLite requires check_same_thread=False for multi-threaded FastAPI access
connect_args: dict[str, bool] = (
    {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
)


def create_db_and_tables() -> None:
    """Initialize database and create all registered SQLModel tables."""
    SQLModel.metadata.create_all(engine)
    # Ensure SQLite file is physically created even before tables are registered
    with engine.connect():
        pass


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    with Session(engine) as session:
        yield session
