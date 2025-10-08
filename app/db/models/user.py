from sqlalchemy import JSON, Boolean, Column, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db import (
    Base,
    async_db_query,
    async_db_update,
    db_query,
    db_update,
    get_id_column,
)


class User(Base):
    """
    User table.
    """

    # ID
    id = get_id_column()
    # Username, unique value
    name = Column(String, index=True, nullable=False)
    # Email
    email = Column(String)
    # Hashed password
    hashed_password = Column(String)
    # Whether the user is active
    is_active = Column(Boolean(), default=True)
    # Whether the user is a superuser
    is_superuser = Column(Boolean(), default=False)
    # Avatar
    avatar = Column(String)
    # Whether OTP is enabled
    is_otp = Column(Boolean(), default=False)
    # OTP secret
    otp_secret = Column(String, default=None)
    # User permissions in JSON format
    permissions = Column(JSON, default=dict)
    # User personalized settings in JSON format
    settings = Column(JSON, default=dict)

    @classmethod
    @db_query
    def get_by_name(cls, db: Session, name: str):
        return db.query(cls).filter(cls.name == name).first()

    @classmethod
    @async_db_query
    async def async_get_by_name(cls, db: AsyncSession, name: str):
        result = await db.execute(select(cls).filter(cls.name == name))
        return result.scalars().first()

    @classmethod
    @db_query
    def get_by_id(cls, db: Session, user_id: int):
        return db.query(cls).filter(cls.id == user_id).first()

    @classmethod
    @async_db_query
    async def async_get_by_id(cls, db: AsyncSession, user_id: int):
        result = await db.execute(select(cls).filter(cls.id == user_id))
        return result.scalars().first()

    @db_update
    def delete_by_name(self, db: Session, name: str):
        user = self.get_by_name(db, name)
        if user:
            user.delete(db, user.id)
        return True

    @async_db_update
    async def async_delete_by_name(self, db: AsyncSession, name: str):
        user = await self.async_get_by_name(db, name)
        if user:
            await user.async_delete(db, user.id)
        return True

    @db_update
    def delete_by_id(self, db: Session, user_id: int):
        user = self.get_by_id(db, user_id)
        if user:
            user.delete(db, user.id)
        return True

    @async_db_update
    async def async_delete_by_id(self, db: AsyncSession, user_id: int):
        user = await self.async_get_by_id(db, user_id)
        if user:
            await user.async_delete(db, user.id)
        return True

    @db_update
    def update_otp_by_name(self, db: Session, name: str, otp: bool, secret: str):
        user = self.get_by_name(db, name)
        if user:
            user.update(db, {"is_otp": otp, "otp_secret": secret})
            return True
        return False

    @async_db_update
    async def async_update_otp_by_name(
        self, db: AsyncSession, name: str, otp: bool, secret: str
    ):
        user = await self.async_get_by_name(db, name)
        if user:
            await user.async_update(db, {"is_otp": otp, "otp_secret": secret})
            return True
        return False
