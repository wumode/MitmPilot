import re
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.core.security import get_password_hash
from app.db import get_async_db
from app.db.models.user import User
from app.db.user_oper import (
    get_current_active_superuser_async,
    get_current_active_user,
    get_current_active_user_async,
)
from app.db.userconfig_oper import UserConfigOper
from app.utils.otp import OtpUtils

router = APIRouter()


@router.get("/", summary="All users", response_model=list[schemas.User])
async def list_users(
    db: AsyncSession = Depends(get_async_db),  # noqa: B008
    current_user: User = Depends(get_current_active_superuser_async),  # noqa: B008
) -> Any:
    """Query user list."""
    return await current_user.async_list(db)


@router.post("/", summary="Add user", response_model=schemas.Response)
async def create_user(
    *,
    db: AsyncSession = Depends(get_async_db),  # noqa: B008
    user_in: schemas.UserCreate,
    current_user: User = Depends(get_current_active_superuser_async),  # noqa: B008
) -> Any:
    """Add user."""
    user = await current_user.async_get_by_name(db, name=user_in.name)
    if user:
        return schemas.Response(success=False, message="User already exists")
    user_info = user_in.model_dump()
    user_info["hashed_password"] = get_password_hash(user_info["password"])
    user_info.pop("password")
    user = await User(**user_info).async_create(db)
    return schemas.Response(success=True if user else False)


@router.put("/", summary="Update user", response_model=schemas.Response)
async def update_user(
    *,
    db: AsyncSession = Depends(get_async_db),  # noqa: B008
    user_in: schemas.UserUpdate,
    current_user: User = Depends(get_current_active_superuser_async),  # noqa: B008
) -> Any:
    """Update user."""
    user_info = user_in.model_dump()
    if user_info.get("password"):
        # Regular expression matches that the password contains at least two of
        # letters, numbers, and special characters
        pattern = r"^(?![a-zA-Z]+$)(?!\d+$)(?![^\da-zA-Z\s]+$).{6,50}$"
        if not re.match(pattern, user_info.get("password")):
            return schemas.Response(
                success=False,
                message="The password must contain at least two of letters, numbers, "
                "and special characters, and the length must be greater than 6 digits",
            )
        user_info["hashed_password"] = get_password_hash(user_info["password"])
        user_info.pop("password")
    user = await current_user.async_get_by_id(db, user_id=user_info["id"])
    user_name = user_info.get("name")
    if not user_name:
        return schemas.Response(success=False, message="Username cannot be empty")
    # New username deduplication
    users = await current_user.async_list(db)
    for u in users:
        if u.name == user_name and u.id != user_info["id"]:
            return schemas.Response(success=False, message="Username is already in use")
    if not user:
        return schemas.Response(success=False, message="User does not exist")
    await user.async_update(db, user_info)
    return schemas.Response(success=True)


@router.get(
    "/config/{key}", summary="Query user configuration", response_model=schemas.Response
)
def get_config(key: str, current_user: User = Depends(get_current_active_user)):  # noqa: B008
    """Query user configuration."""
    value = UserConfigOper().get(username=current_user.name, key=key)
    return schemas.Response(success=True, data={"value": value})


@router.post(
    "/config/{key}",
    summary="Update user configuration",
    response_model=schemas.Response,
)
def set_config(
    key: str,
    value: Annotated[list | dict | bool | int | str | None, Body()] = None,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """Update user configuration."""
    UserConfigOper().set(username=current_user.name, key=key, value=value)
    return schemas.Response(success=True)


@router.delete("/id/{user_id}", summary="Delete user", response_model=schemas.Response)
async def delete_user_by_id(
    *,
    db: AsyncSession = Depends(get_async_db),  # noqa: B008
    user_id: int,
    current_user: User = Depends(get_current_active_superuser_async),  # noqa: B008
) -> Any:
    """Delete user by unique ID."""
    user = await current_user.async_get_by_id(db, user_id=user_id)
    if not user:
        return schemas.Response(success=False, message="User does not exist")
    await current_user.async_delete(db, user_id)
    return schemas.Response(success=True)


@router.delete(
    "/name/{user_name}", summary="Delete user", response_model=schemas.Response
)
async def delete_user_by_name(
    *,
    db: AsyncSession = Depends(get_async_db),  # noqa: B008
    user_name: str,
    current_user: User = Depends(get_current_active_superuser_async),  # noqa: B008
) -> Any:
    """Delete user by username."""
    user = await current_user.async_get_by_name(db, name=user_name)
    if not user:
        return schemas.Response(success=False, message="User does not exist")
    await current_user.async_delete(db, user.id)
    return schemas.Response(success=True)


@router.get("/{username}", summary="User details", response_model=schemas.User)
async def read_user_by_name(
    username: str,
    current_user: User = Depends(get_current_active_user_async),  # noqa: B008
    db: AsyncSession = Depends(get_async_db),  # noqa: B008
) -> Any:
    """Query user details."""
    user = await current_user.async_get_by_name(db, name=username)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User does not exist",
        )
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(status_code=400, detail="Insufficient user permissions")
    return user


@router.post(
    "/otp/generate",
    summary="Generate otp verification uri",
    response_model=schemas.Response,
)
def otp_generate(
    current_user: User = Depends(get_current_active_user),  # noqa: B008
) -> Any:
    secret, uri = OtpUtils.generate_secret_key(current_user.name)
    return schemas.Response(success=secret != "", data={"secret": secret, "uri": uri})


@router.post(
    "/otp/judge",
    summary="Judge whether the otp verification is passed",
    response_model=schemas.Response,
)
async def otp_judge(
    data: schemas.OtpJudge,
    db: AsyncSession = Depends(get_async_db),  # noqa: B008
    current_user: User = Depends(get_current_active_user_async),  # noqa: B008
) -> Any:
    uri = data.uri
    otp_password = data.otp_password
    if not OtpUtils.is_legal(uri, otp_password):
        return schemas.Response(success=False, message="Verification code error")
    await current_user.async_update_otp_by_name(
        db, current_user.name, True, OtpUtils.get_secret(uri)
    )
    return schemas.Response(success=True)


@router.post(
    "/otp/disable",
    summary="Disable otp verification for the current user",
    response_model=schemas.Response,
)
async def otp_disable(
    db: AsyncSession = Depends(get_async_db),  # noqa: B008
    current_user: User = Depends(get_current_active_user_async),  # noqa: B008
) -> Any:
    await current_user.async_update_otp_by_name(db, current_user.name, False, "")
    return schemas.Response(success=True)


@router.get(
    "/otp/{userid}",
    summary="Judge whether the current user has enabled otp verification",
    response_model=schemas.Response,
)
async def otp_enable(userid: str, db: AsyncSession = Depends(get_async_db)) -> Any:  # noqa: B008
    user: User = await User.async_get_by_name(db, userid)
    if not user:
        return schemas.Response(success=False)
    return schemas.Response(success=user.is_otp)
