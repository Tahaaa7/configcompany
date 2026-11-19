from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine
from app.config import DATABASE_URL
from app.models import Base

cfg = context.config
if cfg.config_file_name: fileConfig(cfg.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction(): context.run_migrations()

def run_migrations_online():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)  # batch: سازگار با SQLite
        with context.begin_transaction(): context.run_migrations()

run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
