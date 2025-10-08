from fastapi import APIRouter

from app.api.endpoints import addon, dashboard, login, mitmproxy, system, user

api_router = APIRouter()

api_router.include_router(addon.router, prefix="/addon", tags=["addon"])
api_router.include_router(mitmproxy.router, prefix="/mitmproxy", tags=["mitmproxy"])
api_router.include_router(login.router, prefix="/login", tags=["login"])
api_router.include_router(user.router, prefix="/user", tags=["user"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
