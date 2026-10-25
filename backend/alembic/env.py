from logging.config import fileConfig
from alembic import context
from app.core.db import Base, engine
from app import models

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata
if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        if engine.dialect.name == 'sqlite':
            # Alembic batch rebuilds referenced tables; validate references after
            # migration. Run migrations with application writers stopped.
            connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, render_as_batch=engine.dialect.name == 'sqlite')
        with context.begin_transaction():
            context.run_migrations()

        if engine.dialect.name == 'sqlite':
            violations = connection.exec_driver_sql('PRAGMA foreign_key_check').all()
            connection.commit()
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            if violations:
                raise RuntimeError('Migration produced foreign key violations')
