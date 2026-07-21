from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth.jwt_tb import get_tb_user
from app.models.schemas import ChatRequest, ChatResponse, DeviceInfo, TbUser

router = APIRouter(prefix="/v1", tags=["copilot"])


def get_orchestrator(request: Request):
    return request.app.state.orchestrator


@router.get("/devices", response_model=list[DeviceInfo])
async def list_devices(
    user_token: tuple[TbUser, str] = Depends(get_tb_user),
    orchestrator=Depends(get_orchestrator),
):
    _, token = user_token
    try:
        return await orchestrator.list_devices(token)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to list devices: {exc}") from exc


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user_token: tuple[TbUser, str] = Depends(get_tb_user),
    orchestrator=Depends(get_orchestrator),
):
    user, token = user_token
    try:
        return await orchestrator.chat(user, token, body)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chat failed: {exc}") from exc
