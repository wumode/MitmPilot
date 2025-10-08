from fastapi import FastAPI

from app.core.config import settings


def init_routers(app: FastAPI):
    """
    Initializes routers.
    """
    from app.api.apiv1 import api_router

    # API router
    app.include_router(api_router, prefix=settings.API_V1_STR)
