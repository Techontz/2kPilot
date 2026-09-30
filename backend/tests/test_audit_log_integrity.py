import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from fxrobot.models import AuditLog, User


def test_audit_rows_cannot_be_modified(owner: User, db: Session) -> None:
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(update(AuditLog).values(action="tampered"))
    db.rollback()


def test_audit_rows_cannot_be_deleted(owner: User, db: Session) -> None:
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(delete(AuditLog))
    db.rollback()


def test_deleting_a_user_keeps_their_audit_history(owner: User, db: Session) -> None:
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": owner.id})
    db.commit()
    entry = db.scalars(select(AuditLog)).one()
    assert entry.actor_user_id is None
    assert entry.action == "user.created"
