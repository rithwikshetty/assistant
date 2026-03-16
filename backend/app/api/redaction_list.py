"""API endpoints for user redaction list management."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from ..auth.dependencies import get_current_user
from ..config.database import get_db
from ..database.models import User, UserRedactionEntry
from ..schemas.redaction_list import (
    RedactionEntryResponse,
    RedactionEntryCreate,
    RedactionEntryUpdate,
)
from ..services.admin import analytics_event_recorder

router = APIRouter(prefix="/users/me/redaction-list", tags=["redaction-list"])


@router.get("", response_model=List[RedactionEntryResponse])
def get_redaction_list(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all redaction entries for the current user."""
    entries = db.query(UserRedactionEntry).filter(
        UserRedactionEntry.user_id == user.id
    ).order_by(UserRedactionEntry.created_at.desc()).all()
    return entries


@router.post("", response_model=RedactionEntryResponse, status_code=status.HTTP_201_CREATED)
def add_redaction_entry(
    payload: RedactionEntryCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new name/term to the user's redaction list."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    
    entry = UserRedactionEntry(
        user_id=user.id,
        name=name,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(entry)
    db.flush()

    # Record stats for redaction entry creation
    analytics_event_recorder.record_redaction_entry_created(db, user.id)

    db.commit()
    db.refresh(entry)
    return entry


@router.put("/{entry_id}", response_model=RedactionEntryResponse)
def update_redaction_entry(
    entry_id: str,
    payload: RedactionEntryUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an existing redaction entry."""
    entry = db.query(UserRedactionEntry).filter(
        UserRedactionEntry.id == entry_id,
        UserRedactionEntry.user_id == user.id,
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        entry.name = name
    
    if payload.is_active is not None:
        entry.is_active = payload.is_active
    
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_redaction_entry(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a name/term from the user's redaction list."""
    entry = db.query(UserRedactionEntry).filter(
        UserRedactionEntry.id == entry_id,
        UserRedactionEntry.user_id == user.id,
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    db.delete(entry)
    db.commit()
