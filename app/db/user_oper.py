from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import verify_token
from app.db import DbOper, get_async_db, get_db
from app.db.models.user import User


def get_current_user(
    db: Session = Depends(get_db),  # noqa: B008
    token_data: schemas.TokenPayload = Depends(verify_token),  # noqa: B008
) -> User:
    """
    Get the current user.
    """
    user = User.get(db, rid=token_data.sub)
    if not user:
        raise HTTPException(status_code=403, detail="User does not exist")
    return user


async def get_current_user_async(
    db: AsyncSession = Depends(get_async_db),  # noqa: B008
    token_data: schemas.TokenPayload = Depends(verify_token),  # noqa: B008
) -> User:
    """
    Asynchronously get the current user.
    """
    user = await User.async_get(db, rid=token_data.sub)
    if not user:
        raise HTTPException(status_code=403, detail="User does not exist")
    return user


def get_current_active_superuser(
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> User:
    """
    Get the current active superuser.
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=400, detail="Insufficient permissions")
    return current_user


def get_current_active_user(
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> User:
    """
    获取当前激活用户
    """
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="用户未激活")
    return current_user


async def get_current_active_superuser_async(
    current_user: User = Depends(get_current_user_async),  # noqa: B008
) -> User:
    """
    Asynchronously get the current active superuser.
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=400, detail="Insufficient permissions")
    return current_user


async def get_current_active_user_async(
    current_user: User = Depends(get_current_user_async),  # noqa: B008
) -> User:
    """
    异步获取当前激活用户
    """
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="用户未激活")
    return current_user


class UserOper(DbOper):
    """
    User management.
    """

    def list(self) -> list[User]:
        """
        Get a list of users.
        """
        return User.list(self._db)  # noqa

    def add(self, **kwargs):
        """
        Add a new user.
        """
        user = User(**kwargs)
        user.create(self._db)  # noqa

    def get_by_name(self, name: str) -> User:
        """
        Get a user by name.
        """
        return User.get_by_name(self._db, name)  # noqa

    def get_permissions(self, name: str) -> dict:
        """
        Get user permissions.
        """
        user = User.get_by_name(self._db, name)  # noqa
        if user:
            return user.permissions or {}
        return {}

    def get_settings(self, name: str) -> dict | None:
        """
        Get user personalized settings, return None if the user does not exist.
        """
        user = User.get_by_name(self._db, name)  # noqa
        if user:
            return user.settings or {}
        return None

    def get_setting(self, name: str, key: str) -> str | None:
        """
        Get a user's personalized setting.
        """
        settings = self.get_settings(name)
        if settings:
            return settings.get(key)
        return None

    def get_name(self, **kwargs) -> str | None:
        """
        Get the username based on the bound account.
        """
        users = self.list()
        for user in users:
            user_setting = user.settings
            if user_setting:
                for k, v in kwargs.items():
                    if user_setting.get(k) == str(v):
                        return user.name
        return None
