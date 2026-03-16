from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional

class ShareResponse(BaseModel):
    share_token: str
    share_url: str  # Full URL for easy copying
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ShareImportResponse(BaseModel):
    conversation_id: str
    title: str
    message: str  # "Conversation imported successfully"

    model_config = ConfigDict(from_attributes=True)
