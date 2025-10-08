from pydantic import BaseModel


class MasterStatus(BaseModel):
    is_running: bool
