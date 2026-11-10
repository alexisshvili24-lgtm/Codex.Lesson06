from alembic import context
from src.database import engine, Base

def run_migrations_online():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()