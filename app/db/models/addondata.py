from sqlalchemy import JSON, Column, String
from sqlalchemy.orm import Session

from app.db import Base, db_query, db_update, get_id_column


class AddonData(Base):
    """
    Addon data table.
    """

    id = get_id_column()
    addon_id = Column(String, nullable=False, index=True)
    key = Column(String, index=True, nullable=False)
    value = Column(JSON)

    @classmethod
    @db_query
    def get_addon_data(cls, db: Session, addon_id: str):
        return db.query(cls).filter(cls.addon_id == addon_id).all()

    @classmethod
    @db_query
    def get_addon_data_by_key(cls, db: Session, addon_id: str, key: str):
        return db.query(cls).filter(cls.addon_id == addon_id, cls.key == key).first()

    @classmethod
    @db_update
    def del_addon_data_by_key(cls, db: Session, addon_id: str, key: str):
        db.query(cls).filter(cls.addon_id == addon_id, cls.key == key).delete()

    @classmethod
    @db_update
    def del_addon_data(cls, db: Session, addon_id: str):
        db.query(cls).filter(cls.addon_id == addon_id).delete()

    @classmethod
    @db_query
    def get_addon_data_by_plugin_id(cls, db: Session, addon_id: str):
        return db.query(cls).filter(cls.addon_id == addon_id).all()
