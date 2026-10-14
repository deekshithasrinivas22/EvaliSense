"""Audit logging service for EvaliSense.

Records immutable audit trail entries for security-critical actions:
- Authentication events
- Role and user management
- File uploads and modifications
- Mark changes and evaluation decisions
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from api.database.models import AuditLog
from utils.logging import get_logger

logger = get_logger(__name__)


def create_audit_log(
    db: Session,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Create an immutable audit log entry."""
    log_entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=json.dumps(details, ensure_ascii=False) if details else None,
        ip_address=ip_address,
        created_at=datetime.utcnow(),
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    logger.info(
        "AUDIT: user=%s action=%s entity=%s#%s",
        user_id, action, entity_type, entity_id,
    )
    return log_entry


def get_audit_logs(
    db: Session,
    entity_type: str | None = None,
    entity_id: int | None = None,
    user_id: int | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    """Retrieve audit log entries with optional filters."""
    query = db.query(AuditLog)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    return query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
