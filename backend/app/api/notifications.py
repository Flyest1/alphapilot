from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.services.notification_service import mark_notification_read

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    repository: Repository = Depends(get_repository),
) -> dict[str, Any]:
    return {
        "notifications": repository.list_notifications(unread_only=unread_only, limit=limit),
        "unread_count": len(repository.list_notifications(unread_only=True)),
    }


@router.post("/read-all")
def read_all_notifications(repository: Repository = Depends(get_repository)) -> dict[str, int]:
    return {"updated_count": repository.mark_all_notifications_read()}


@router.post("/{notification_id}/read")
def read_notification(
    notification_id: str,
    repository: Repository = Depends(get_repository),
) -> dict[str, Any]:
    row = mark_notification_read(repository, notification_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="notification not found")
    return row
