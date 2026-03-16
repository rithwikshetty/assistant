from pydantic import BaseModel, Field
from typing import List, Literal


class VoiceStatusResponse(BaseModel):
    status: Literal["available", "disabled"]
    supported_formats: List[str] = Field(default_factory=list)
    max_file_size_mb: int


class VoiceTranscriptionResponse(BaseModel):
    text: str

