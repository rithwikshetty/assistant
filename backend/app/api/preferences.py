from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..auth.dependencies import get_current_user
from ..config.database import get_db
from ..database.models import User
from ..schemas.preferences import PreferencesResponse, PreferencesUpdate
from ..services.preferences_service import PreferencesService

router = APIRouter(prefix="/users/me/preferences", tags=["preferences"])
service = PreferencesService()


@router.get("", response_model=PreferencesResponse)
def get_preferences(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pref = service.get_preferences(user=user, db=db)
    return PreferencesResponse(
        theme=pref.theme,
        custom_instructions=pref.custom_instructions,
        notification_sound=pref.notification_sound,
        timezone=pref.timezone,
        locale=pref.locale,
        updated_at=pref.updated_at.isoformat() if pref.updated_at else None,
    )


@router.put("", response_model=PreferencesResponse, status_code=status.HTTP_200_OK)
def update_preferences(
    payload: PreferencesUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        pref = service.update_preferences(
            user=user,
            db=db,
            theme=payload.theme,
            custom_instructions=payload.custom_instructions,
            notification_sound=payload.notification_sound,
            timezone=payload.timezone,
            locale=payload.locale,
        )
        return PreferencesResponse(
            theme=pref.theme,
            custom_instructions=pref.custom_instructions,
            notification_sound=pref.notification_sound,
            timezone=pref.timezone,
            locale=pref.locale,
            updated_at=pref.updated_at.isoformat() if pref.updated_at else None,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
