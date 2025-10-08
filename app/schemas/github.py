from pydantic import BaseModel


class GithubItem(BaseModel):
    name: str
    path: str
    sha: str
    size: int
    url: str
    git_url: str
    download_url: str | None
    type: str
