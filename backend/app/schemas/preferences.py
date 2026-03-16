from pydantic import BaseModel, constr
from typing import Optional, Literal

Theme = Literal['light', 'dark']
CustomInstructions = constr(max_length=2000)  # Generous but bounded


class PreferencesResponse(BaseModel):
    theme: Optional[Theme] = None
    custom_instructions: Optional[str] = None
    notification_sound: Optional[bool] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
    updated_at: Optional[str] = None


class PreferencesUpdate(BaseModel):
    theme: Optional[Theme] = None
    custom_instructions: Optional[CustomInstructions] = None
    notification_sound: Optional[bool] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
