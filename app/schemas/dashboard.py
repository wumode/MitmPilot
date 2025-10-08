from pydantic import BaseModel


class ScheduleInfo(BaseModel):
    # ID
    id: str | None = None
    # Name
    name: str | None = None
    # Provider
    provider: str | None = None
    # Status
    status: str | None = None
    # Next run time
    next_run: str | None = None
