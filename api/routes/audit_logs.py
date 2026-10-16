"""Audit log routes for HOD oversight."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.auth.dependencies import require_hod
from api.database.models import User
from api.database.session import get_db
from api.services.audit_service import get_audit_logs

router = APIRouter(prefix="/api/audit-logs", tags=["Audit Logs"])


@router.get("")
def list_audit_logs(
    entity_type: str | None = Query(None, description="Filter by entity type"),
    entity_id: int | None = Query(None, description="Filter by entity ID"),
    user_id: int | None = Query(None, description="Filter by user ID"),
    action: str | None = Query(None, description="Filter by action"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Retrieve audit logs (HOD only)."""
    logs = get_audit_logs(
        db=db,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return [log.to_dict() for log in logs]
