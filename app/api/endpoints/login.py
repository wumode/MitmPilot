from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from app import schemas
from app.chain.user import UserChain
from app.core import security
from app.core.config import settings
from app.helper.wallpaper import WallpaperHelper

router = APIRouter()


@router.post("/access-token", summary="Get token", response_model=schemas.Token)
def login_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    otp_password: Annotated[str | None, Form()] = None,
) -> Any:
    """
    Get authentication token
    """
    success, user_or_message = UserChain().user_authenticate(
        username=form_data.username, password=form_data.password, mfa_code=otp_password
    )

    if not success:
        raise HTTPException(status_code=401, detail=user_or_message)

    # User level
    level = 1
    return schemas.Token(
        access_token=security.create_access_token(
            userid=user_or_message.id,
            username=user_or_message.name,
            super_user=user_or_message.is_superuser,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            level=level,
        ),
        token_type="bearer",
        super_user=user_or_message.is_superuser,
        user_id=user_or_message.id,
        user_name=user_or_message.name,
        avatar=user_or_message.avatar,
        level=level,
        permissions=user_or_message.permissions or {},
    )


@router.get(
    "/wallpaper", summary="Login page wallpaper", response_model=schemas.Response
)
def wallpaper() -> Any:
    """
    Get login page wallpaper
    """
    url = WallpaperHelper().get_wallpaper()
    if url:
        return schemas.Response(success=True, message=url)
    return schemas.Response(success=False)


@router.get(
    "/wallpapers", summary="Login page wallpapers list", response_model=list[str]
)
def wallpapers() -> Any:
    """
    Get login page wallpapers
    """
    return WallpaperHelper().get_wallpapers()
