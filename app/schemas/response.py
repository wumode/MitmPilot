from pydantic import BaseModel, Field


class Response(BaseModel):
    # Status
    success: bool
    # Message text
    message: str | None = None
    # Data
    data: dict | list | None = Field(default_factory=dict)
