"""Audit trail service (SRS 3.13).

Every administrator mutation writes an ``AuditLog`` row. The trail itself is
read-only in the UI - there is intentionally no edit or delete endpoint.
"""
from __future__ import annotations

from flask import request

from ..extensions import db
from ..models import AuditLog, User


def log_action(
    actor: User | None,
    action: str,
    target: str = "",
    notes: str = "",
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        admin_id=actor.id if actor is not None else None,
        admin_name=(actor.name if actor is not None else "system"),
        action=action[:40],
        target=(target or "")[:80] or None,
        notes=(notes or "")[:255] or None,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def audit_on_request() -> str:
    """Best-effort source endpoint note for audit entries."""
    try:
        return request.method + " " + request.path
    except RuntimeError:  # outside of request context
        return ""


def recent(limit: int = 100):
    return (
        AuditLog.query
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .all()
    )
