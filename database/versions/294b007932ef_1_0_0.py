"""2.0.0

Revision ID: 294b007932ef
Revises:
Create Date: 2024-07-20 08:43:40.741251

"""

import secrets

from app.core.config import settings
from app.core.security import get_password_hash
from app.db import SessionFactory
from app.db.models import User
from app.db.systemconfig_oper import SystemConfigOper
from app.log import logger

# revision identifiers, used by Alembic.
revision = "294b007932ef"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Initialize the database.
    """
    with SessionFactory() as db:
        # Initialize superuser
        _user = User.get_by_name(db=db, name=settings.SUPERUSER)
        if not _user:
            if settings.SUPERUSER_PASSWORD:
                init_password = settings.SUPERUSER_PASSWORD
            else:
                # Generate random password
                init_password = secrets.token_urlsafe(16)
                logger.info(
                    f"【Initial password for superuser】 {init_password} Please change it after logging in. Note: This password will only be displayed once, please save it."
                )
            _user = User(
                name=settings.SUPERUSER,
                hashed_password=get_password_hash(init_password),
                email="admin@mitmpilot.com",
                is_superuser=True,
                avatar="",
            )
            _user.create(db)
        # Initialize local storage
        _systemconfig = SystemConfigOper()


def downgrade() -> None:
    pass
