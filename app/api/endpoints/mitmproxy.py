from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import FileResponse

from app import schemas
from app.core.config import settings
from app.core.master import MitmManager
from app.db.models import User
from app.db.user_oper import get_current_active_superuser_async

router = APIRouter()


@router.post("/start", summary="Start Mitmproxy", response_model=schemas.Response)
async def start_mitm(_: User = Depends(get_current_active_superuser_async)):  # noqa: B008
    """
    Start the mitmproxy service.
    """
    mitm_manager = MitmManager()
    if mitm_manager.is_running:
        raise HTTPException(status_code=409, detail="Mitmproxy is already running.")
    await mitm_manager.start()
    return schemas.Response(success=True, message="Mitmproxy started successfully.")


@router.post("/stop", summary="Stop Mitmproxy", response_model=schemas.Response)
async def stop_mitm(_: User = Depends(get_current_active_superuser_async)):  # noqa: B008
    """
    Stop the mitmproxy service.
    """
    mitm_manager = MitmManager()
    if not mitm_manager.is_running:
        raise HTTPException(status_code=404, detail="Mitmproxy is not running.")
    await mitm_manager.stop()
    return schemas.Response(success=True, message="Mitmproxy stopped successfully.")


@router.get(
    "/status", summary="Get Mitmproxy status", response_model=schemas.MasterStatus
)
async def get_mitm_status(
    _: User = Depends(get_current_active_superuser_async),  # noqa: B008
) -> schemas.MasterStatus:
    """
    Get the current status of the mitmproxy service.
    """
    return schemas.MasterStatus(is_running=MitmManager().is_running)


@router.get("/cert/download", summary="Download Mitmproxy certificate")
async def download_mitm_cert() -> FileResponse:
    """
    Download the mitmproxy certificate file for installation on the client.
    """
    cert_path = settings.CONFIG_PATH / settings.CERT_FILENAME
    if not cert_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Certificate file {settings.CERT_FILENAME!r} not found.",
        )
    return FileResponse(
        path=str(cert_path),
        media_type="application/octet-stream",
        filename=settings.CERT_FILENAME,
    )
