from pydantic import BaseModel, ConfigDict, Field


# Shared properties
class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 用户名
    name: str
    # 邮箱，未启用
    email: str | None = None
    # 状态
    is_active: bool | None = True
    # 超级管理员
    is_superuser: bool = False
    # 头像
    avatar: str | None = None
    # 是否开启二次验证
    is_otp: bool | None = False
    # 权限
    permissions: dict | None = Field(default_factory=dict)
    # 个性化设置
    settings: dict | None = Field(default_factory=dict)


# Properties to receive via API on creation
class UserCreate(UserBase):
    name: str
    email: str | None = None
    password: str
    settings: dict | None = Field(default_factory=dict)
    permissions: dict | None = Field(default_factory=dict)


# Properties to receive via API on update
class UserUpdate(UserBase):
    id: int
    name: str
    email: str | None = None
    password: str | None = None
    settings: dict | None = Field(default_factory=dict)
    permissions: dict | None = Field(default_factory=dict)


class UserInDBBase(UserBase):
    id: int | None = None


# Additional properties to return via API
class User(UserInDBBase):
    name: str
    email: str | None = None


# Additional properties stored in DB
class UserInDB(UserInDBBase):
    hashed_password: str


class OtpJudge(BaseModel):
    uri: str
    otp_password: str = Field(alias="otpPassword")
