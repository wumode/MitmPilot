from sqlalchemy import JSON, Column, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db import Base, async_db_query, db_query, db_update, get_id_column


class SystemConfig(Base):
    """
    Configuration table.
    """

    id = get_id_column()
    # Primary key
    key = Column(String, index=True)
    # Value
    value = Column(JSON)

    @classmethod
    @db_query
    def get_by_key(cls, db: Session, key: str):
        return db.query(cls).filter(cls.key == key).first()

    @classmethod
    @async_db_query
    async def async_get_by_key(cls, db: AsyncSession, key: str):
        result = await db.execute(select(cls).where(cls.key == key))
        return result.scalar_one_or_none()

    @db_update
    def delete_by_key(self, db: Session, key: str):
        systemconfig = self.get_by_key(db, key)
        if systemconfig:
            systemconfig.delete(db, systemconfig.id)
        return True
