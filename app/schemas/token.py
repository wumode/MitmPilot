from pydantic import BaseModel, Field


class Token(BaseModel):
    # 令牌
    access_token: str
    # 令牌类型
    token_type: str
    # 超级用户
    super_user: bool
    # 用户ID
    user_id: int
    # 用户名
    user_name: str
    # 头像
    avatar: str | None = None
    # 权限级别
    level: int = 1
    # 详细权限
    permissions: dict | None = Field(default_factory=dict)


class TokenPayload(BaseModel):
    # 用户ID
    sub: int | None = None
    # 用户名
    username: str = None
    # 超级用户
    super_user: bool | None = None
    # 权限级别
    level: int = None
    # 令牌用途 authentication\resource
    purpose: str | None = None
