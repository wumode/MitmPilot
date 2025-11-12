from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app import schemas
from app.core.security import verify_apitoken, verify_token
from app.scheduler import Scheduler
from app.utils.system import SystemUtils

router = APIRouter()


@router.get(
    "/schedule",
    summary="Background services",
    response_model=list[schemas.ScheduleInfo],
)
async def schedule(_: schemas.TokenPayload = Depends(verify_token)) -> Any:  # noqa: B008
    """Query background service information."""
    return Scheduler().list_tasks()


@router.get(
    "/schedule2",
    summary="Background services (API_TOKEN)",
    response_model=list[schemas.ScheduleInfo],
)
async def schedule2(_: Annotated[str, Depends(verify_apitoken)]) -> Any:  # noqa: B008
    """Query background service information by API_TOKEN authentication (?token=xxx)"""
    return await schedule()


@router.get("/cpu", summary="Get current CPU usage", response_model=int)
def cpu(_: schemas.TokenPayload = Depends(verify_token)) -> Any:  # noqa: B008
    """Get current CPU usage."""
    return SystemUtils.cpu_usage()


@router.get("/cpu2", summary="Get current CPU usage (API_TOKEN)", response_model=int)
def cpu2(_: Annotated[str, Depends(verify_apitoken)]) -> Any:  # noqa: B008
    """Get current CPU usage API_TOKEN authentication (?token=xxx)"""
    return cpu()


@router.get(
    "/memory",
    summary="Get current memory usage and usage rate",
    response_model=list[int],
)
def memory(_: schemas.TokenPayload = Depends(verify_token)) -> Any:  # noqa: B008
    """Get current memory usage rate."""
    return SystemUtils.memory_usage()


@router.get(
    "/memory2",
    summary="Get current memory usage and usage rate (API_TOKEN)",
    response_model=list[int],
)
def memory2(_: Annotated[str, Depends(verify_apitoken)]) -> Any:  # noqa: B008
    """Get the current memory usage rate API_TOKEN authentication (?token=xxx)"""
    return memory()


@router.get("/network", summary="Get current network traffic", response_model=list[int])
def network(_: schemas.TokenPayload = Depends(verify_token)) -> Any:  # noqa: B008
    """Get current network traffic (uplink and downlink traffic, unit:

    bytes/s)
    """
    return SystemUtils.network_usage()


@router.get(
    "/network2",
    summary="Get current network traffic (API_TOKEN)",
    response_model=list[int],
)
def network2(_: Annotated[str, Depends(verify_apitoken)]) -> Any:  # noqa: B008
    """Get current network traffic API_TOKEN authentication (?token=xxx)"""
    return network()
