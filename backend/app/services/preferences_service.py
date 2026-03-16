from sqlalchemy.orm import Session
from ..database.models import User, UserPreference
from typing import Optional
from ..utils.timezone_context import normalize_locale, normalize_timezone_name

DEFAULT_THEME = None  # Use client/app default when None


class PreferencesService:
    def get_preferences(self, user: User, db: Session) -> UserPreference:
        pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
        if pref is None:
            pref = UserPreference(user_id=str(user.id), theme=DEFAULT_THEME)
            db.add(pref)
            db.commit()
            db.refresh(pref)
        return pref

    def update_preferences(
        self,
        user: User,
        db: Session,
        *,
        theme: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        notification_sound: Optional[bool] = None,
        timezone: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> UserPreference:
        pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
        if pref is None:
            pref = UserPreference(user_id=str(user.id))
            db.add(pref)

        if theme is not None:
            pref.theme = theme

        if custom_instructions is not None:
            pref.custom_instructions = custom_instructions

        if notification_sound is not None:
            pref.notification_sound = notification_sound

        if timezone is not None:
            pref.timezone = normalize_timezone_name(timezone)

        if locale is not None:
            pref.locale = normalize_locale(locale)

        db.commit()
        db.refresh(pref)
        return pref
