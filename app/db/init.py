from alembic.command import upgrade
from alembic.config import Config

from app.core.config import settings
from app.db import Base, DBEngine
from app.log import logger


def init_db():
    """
    Initialize the database.
    """
    # Create all tables.
    Base.metadata.create_all(bind=DBEngine)  # noqa


def update_db():
    """
    Update the database.
    """
    script_location = settings.ROOT_PATH / "database"
    try:
        alembic_cfg = Config()
        alembic_cfg.set_main_option("script_location", str(script_location))

        # Set different URLs based on the database type.
        if settings.DB_TYPE.lower() == "postgresql":
            if settings.DB_POSTGRESQL_PASSWORD:
                db_url = f"postgresql://{settings.DB_POSTGRESQL_USERNAME}:{settings.DB_POSTGRESQL_PASSWORD}@{settings.DB_POSTGRESQL_HOST}:{settings.DB_POSTGRESQL_PORT}/{settings.DB_POSTGRESQL_DATABASE}"
            else:
                db_url = f"postgresql://{settings.DB_POSTGRESQL_USERNAME}@{settings.DB_POSTGRESQL_HOST}:{settings.DB_POSTGRESQL_PORT}/{settings.DB_POSTGRESQL_DATABASE}"
        else:
            db_location = settings.CONFIG_PATH / "user.db"
            db_url = f"sqlite:///{db_location}"

        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Database update failed: {str(e)}")
