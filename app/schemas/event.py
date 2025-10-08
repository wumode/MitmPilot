from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.addon import AddonService


class BaseEventData(BaseModel):
    """Base class for event data, all specific event data classes should inherit from
    this class."""

    pass


class ChainEventData(BaseEventData):
    """Base class for chain event data, all specific event data classes should inherit
    from this class."""

    pass


class AuthCredentials(ChainEventData):
    """Data model for AuthVerification event."""

    # Input parameters
    username: str | None = Field(
        None, description="Username, applicable to 'password' authentication type"
    )
    password: str | None = Field(
        None, description="User password, applicable to 'password' authentication type"
    )
    mfa_code: str | None = Field(
        None,
        description="One-time password, currently only applicable to 'password' "
        "authentication type",
    )
    code: str | None = Field(
        None,
        description="Authorization code, applicable to 'authorization_code' "
        "authentication type",
    )
    grant_type: str = Field(
        ...,
        description="Authentication type, such as 'password', "
        "'authorization_code', 'client_credentials'",
    )
    # Output parameters
    # When grant_type is authorization_code, the output parameters include username,
    # token, channel, service
    token: str | None = Field(default=None, description="Authentication token")
    channel: str | None = Field(default=None, description="Authentication channel")
    service: str | None = Field(default=None, description="Service name")

    @model_validator(mode="before")
    @classmethod
    def check_fields_based_on_grant_type(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Run before any field validation to process raw input data."""
        grant_type = values.get("grant_type")

        # 1. Set the default value of grant_type
        if not grant_type:
            values["grant_type"] = "password"
            grant_type = "password"

        # 2. Conditional field check based on grant_type
        if grant_type == "password":
            if not values.get("username") or not values.get("password"):
                raise ValueError(
                    "username and password are required for grant_type 'password'"
                )

        elif grant_type == "authorization_code":
            if not values.get("code"):
                raise ValueError("code is required for grant_type 'authorization_code'")

        return values


class AuthInterceptCredentials(ChainEventData):
    """Data model for AuthIntercept event."""

    # Input parameters
    username: str | None = Field(..., description="Username")
    channel: str = Field(..., description="Authentication channel")
    service: str = Field(..., description="Service name")
    status: str = Field(
        ...,
        description="Authentication status, including 'triggered' for authentication "
        "triggered and 'completed' for authentication successful",
    )
    token: str | None = Field(default=None, description="Authentication token")

    # Output parameters
    source: str = Field(
        default="Unknown interception source", description="Interception source"
    )
    cancel: bool = Field(default=False, description="Whether to cancel authentication")


class ConfigChangeEventData(BaseEventData):
    """Data model for ConfigChange event."""

    key: str = Field(..., description="The key of the configuration item")
    value: Any | None = Field(
        default=None, description="The new value of the configuration item"
    )
    change_type: str = Field(
        default="update",
        description="The change type of the configuration item, such as 'add', "
        "'update', 'delete'",
    )


class AddonServiceRegistration(ChainEventData):
    addon_id: str = Field(..., description="the addon id")
    addon_name: str | None = Field(default=None, description="the addon name")
    services: list[AddonService] = Field(
        default_factory=list, description="services to register"
    )

    class Config:
        arbitrary_types_allowed = True
