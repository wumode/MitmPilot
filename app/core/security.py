import datetime
from typing import Annotated, Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, Response, Security, status
from fastapi.security import (
    APIKeyCookie,
    APIKeyHeader,
    APIKeyQuery,
    OAuth2PasswordBearer,
)

from app import schemas
from app.core.config import settings
from app.log import logger

ph = PasswordHasher()
ALGORITHM = "HS256"

# OAuth2PasswordBearer for JWT Token authentication
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)

# API KEY authentication via Header
api_key_header = APIKeyHeader(
    name="X-API-KEY", auto_error=False, scheme_name="api_key_header"
)

# API KEY authentication via QUERY
api_key_query = APIKeyQuery(
    name="apikey", auto_error=False, scheme_name="api_key_query"
)

# API TOKEN 通过 QUERY 认证
api_token_query = APIKeyQuery(
    name="token", auto_error=False, scheme_name="api_token_query"
)

# RESOURCE TOKEN 通过 Cookie 认证
resource_token_cookie = APIKeyCookie(
    name=settings.PROJECT_NAME, auto_error=False, scheme_name="resource_token_cookie"
)


def __verify_token(token: str, purpose: str = "authentication") -> schemas.TokenPayload:
    """Authenticates and parses the content of a JWT Token.

    :param token: JWT token
    :param purpose: Expected token purpose, defaults to "authentication"
    :return: Token payload data containing user identity information
    :raises HTTPException: If the token is invalid or the purpose does not match
    """
    try:
        if purpose == "resource":
            secret_key = settings.RESOURCE_SECRET_KEY
        else:
            secret_key = settings.SECRET_KEY

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"{purpose} token not found",
            )

        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])

        token_payload = schemas.TokenPayload(**payload)

        if token_payload.purpose != purpose:
            raise jwt.InvalidTokenError("Token purpose does not match")

        return schemas.TokenPayload(**payload)
    except (jwt.DecodeError, jwt.InvalidTokenError, jwt.ImmatureSignatureError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
        ) from None


def __get_api_key(
    key_query: Annotated[str | None, Security(api_key_query)] = None,
    key_header: Annotated[str | None, Security(api_key_header)] = None,
) -> str | None:
    """Gets the API Key from the URL query parameters or request header, prioritizing
    the URL parameter.

    :param key_query: The `apikey` query parameter in the URL
    :param key_header: The `X-API-KEY` parameter in the request header
    :return: The API Key from the URL or request header, or None if not found
    """
    return key_query or key_header


def __get_api_token(
    token_query: Annotated[str | None, Security(api_token_query)] = None,
) -> str | None:
    """从 URL 查询参数中获取 API Token :param token_query: 从 URL 中的 `token` 查询参数获取 API Token
    :return: 返回获取到的 API Token，若无则返回 None."""
    return token_query


def __verify_key(key: str, expected_key: str, key_type: str) -> str:
    """Generic API Key or Token validation function.

    :param key: The API Key or Token from the request
    :param expected_key: The expected API Key or Token from the system configuration for
        validation
    :param key_type: The type of the key (e.g., "API_KEY" or "API_TOKEN") for error
        messages
    :return: The validated API Key or Token
    :raises HTTPException: If validation fails, raises a 401 error
    """
    if key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{key_type} validation failed",
        )
    return key


def create_access_token(
    userid: str | Any,
    username: str,
    super_user: bool | None = False,
    expires_delta: datetime.timedelta | None = None,
    level: int = 1,
    purpose: str = "authentication",
) -> str:
    """Creates a JWT access token containing user ID, username, superuser status, and
    permission level.

    :param userid: The user's unique identifier, usually a string or integer
    :param username: The username for the user's account
    :param super_user: Whether the user is a superuser, defaults to False
    :param expires_delta: The token's validity period. If not provided, a default
        expiration time is used based on the purpose.
    :param level: The user's permission level, defaults to 1
    :param purpose: The purpose of the token, "authentication" or "resource"
    :return: The encoded JWT token string
    :raises ValueError: If expires_delta is negative
    """
    if purpose == "resource":
        default_expire = datetime.timedelta(
            seconds=settings.RESOURCE_ACCESS_TOKEN_EXPIRE_SECONDS
        )
        secret_key = settings.RESOURCE_SECRET_KEY
    else:
        default_expire = datetime.timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        secret_key = settings.SECRET_KEY

    if expires_delta is not None:
        if expires_delta.total_seconds() <= 0:
            raise ValueError("Expiration time must be a positive number")
        expire = datetime.datetime.now(datetime.UTC) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.UTC) + default_expire

    to_encode = {
        "exp": expire,
        "iat": datetime.datetime.now(datetime.UTC),
        "sub": str(userid),
        "username": username,
        "super_user": super_user,
        "level": level,
        "purpose": purpose,
    }

    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=ALGORITHM)
    return encoded_jwt


def __set_or_refresh_resource_token_cookie(
    request: Request, response: Response, payload: schemas.TokenPayload
):
    """Sets the resource token Cookie.

    :param request: Contains request-related context data
    :param response: Used to set the Cookie in the server response
    :param payload: The authenticated TokenPayload object
    """
    resource_token = request.cookies.get(settings.PROJECT_NAME)

    if resource_token:
        # Check the remaining time of the token
        try:
            decoded_token = jwt.decode(
                resource_token, settings.RESOURCE_SECRET_KEY, algorithms=[ALGORITHM]
            )
            exp = decoded_token.get("exp")
            if exp:
                remaining_time = datetime.datetime.fromtimestamp(
                    exp, tz=datetime.UTC
                ) - datetime.datetime.now(datetime.UTC)
                # Refresh the token in advance based on the remaining duration
                if remaining_time < datetime.timedelta(
                    seconds=(settings.RESOURCE_ACCESS_TOKEN_EXPIRE_SECONDS / 3)
                ):
                    raise jwt.ExpiredSignatureError
        except jwt.PyJWTError:
            logger.debug("Token error occurred. refreshing token")
        except Exception as e:
            logger.debug(f"Unexpected error occurred while decoding token: {e}")
        else:
            # If the token is valid and not about to expire, no need to refresh
            return

    # Create a new resource access token
    resource_token_expires = datetime.timedelta(
        seconds=settings.RESOURCE_ACCESS_TOKEN_EXPIRE_SECONDS
    )
    resource_token = create_access_token(
        userid=payload.sub,
        username=payload.username,
        super_user=payload.super_user,
        expires_delta=resource_token_expires,
        level=payload.level,
        purpose="resource",
    )

    # Set a session-level HttpOnly Cookie
    response.set_cookie(
        key=settings.PROJECT_NAME,
        value=resource_token,
        httponly=True,
        secure=request.url.scheme
        == "https",  # Set the secure attribute based on the current request's protocol
        samesite="lax",  # Different browsers may handle "Strict" differently,
        # so set SameSite to "Lax" to balance security and compatibility
        path="/",
    )


def verify_token(
    request: Request, response: Response, token: Annotated[str, Security(oauth2_scheme)]
) -> schemas.TokenPayload:
    """Verifies the JWT token and automatically handles writing the resource_token.

    :param request: The request object, used to access cookies and request information
    :param response: The response object, used to set cookies
    :param token: The JWT token from the Authorization header
    :return: The parsed TokenPayload
    :raises HTTPException: If the token is invalid or the purpose does not match
    """
    # Verify and parse the JWT authentication token
    payload = __verify_token(token=token, purpose="authentication")

    # 如果没有 resource_token，生成并写入到 Cookie
    __set_or_refresh_resource_token_cookie(request, response, payload)

    return payload


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        ph.verify(hashed_password, plain_password)
        return True
    except VerifyMismatchError:
        return False


def verify_apikey(apikey: Annotated[str, Security(__get_api_key)]) -> str:
    """Authenticates using an API Key.

    :param apikey: The API Key, obtained from the URL query parameter apikey=xxx
    :return: The validated API Key
    """
    return __verify_key(apikey, settings.API_TOKEN, "apikey")


def verify_apitoken(token: Annotated[str, Security(__get_api_token)]) -> str:
    """使用 API Token 进行身份认证 :param token: API Token，从 URL 查询参数中获取 token=xxx :return: 验通过的
    API Token."""
    return __verify_key(token, settings.API_TOKEN, "token")


def verify_resource_token(
    resource_token: Annotated[str, Security(resource_token_cookie)],
) -> schemas.TokenPayload:
    """验证资源访问令牌（从 Cookie 中获取） :param resource_token: 从 Cookie 中获取的资源访问令牌 :return: 解析后的
    TokenPayload :raises HTTPException: 如果资源访问令牌无效."""
    # 验证并解析资源访问令牌
    return __verify_token(token=resource_token, purpose="resource")


def get_password_hash(password: str) -> str:
    return ph.hash(password)
