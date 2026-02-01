"""Alembic environment; uses app config for database URL."""
import os
import sys

# Add backend/app to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)
os.chdir(backend_dir)

from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy.engine.url import make_url
from sqlalchemy.pool import NullPool
# Import from app (backend/app)
from app.config import settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def _sync_db_url() -> str:
    """
    Alembic runs migrations with a synchronous driver.
    If the app uses a plain `postgresql://...` URL, force psycopg.
    """
    url = make_url(settings.database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    # IMPORTANT: `str(URL)` redacts the password (renders '***').
    # Alembic needs the real password to connect.
    return url.render_as_string(hide_password=False)


# Override sqlalchemy.url from app settings (escape % for configparser)
config.set_main_option("sqlalchemy.url", _sync_db_url().replace("%", "%%"))

target_metadata = Base.metadata

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    conf = config.get_section(config.config_ini_section, {}) or {}
    url = _sync_db_url()
    conf["sqlalchemy.url"] = url
    # Supavisor transaction mode (port 6543) does not support prepared statements.
    connect_args_postgres = {}
    try:
        parsed = make_url(url)
        if parsed.port == 6543:
            connect_args_postgres = {"prepare_threshold": None}
    except Exception:
        connect_args_postgres = {}
    connectable = engine_from_config(
        conf,
        prefix="sqlalchemy.",
        poolclass=NullPool,
        connect_args=connect_args if settings.database_url.startswith("sqlite") else connect_args_postgres,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
