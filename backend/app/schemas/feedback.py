from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import datetime


SEVERITY_VALUES = ("low", "medium", "high")
RATING_VALUES = ("up", "down")


class BugReportCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=1, max_length=10_000)
    severity: str = Field("medium", description="one of: low|medium|high")

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        v_lower = (v or "").lower()
        if v_lower not in SEVERITY_VALUES:
            raise ValueError(f"severity must be one of {SEVERITY_VALUES}")
        return v_lower


class BugReportResponse(BaseModel):
    id: str
    user_id: str
    user_email: str
    user_name: str | None
    title: str
    severity: str
    description: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageFeedbackCreate(BaseModel):
    message_id: str = Field(..., min_length=1, max_length=36)
    rating: str = Field(..., description="one of: up|down")

    time_saved_minutes: int | None = Field(None, ge=0, le=100000)
    improvement_notes: str | None = Field(None, max_length=2000)
    issue_description: str | None = Field(None, max_length=2000)
    time_spent_minutes: int | None = Field(None, ge=0, le=100000)

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: str) -> str:
        v_lower = (v or "").lower()
        if v_lower not in RATING_VALUES:
            raise ValueError(f"rating must be one of {RATING_VALUES}")
        return v_lower

    @field_validator("improvement_notes", "issue_description", mode="before")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @field_validator("time_saved_minutes", "time_spent_minutes")
    @classmethod
    def ensure_positive_minutes(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("minutes must be greater than zero")
        return value

    @model_validator(mode="after")
    def validate_required_fields(cls, data: "MessageFeedbackCreate") -> "MessageFeedbackCreate":
        rating = data.rating
        if rating == "up":
            if data.time_saved_minutes is None:
                raise ValueError("time_saved_minutes is required for thumbs up feedback")
        elif rating == "down":
            if data.time_spent_minutes is None:
                raise ValueError("time_spent_minutes is required for thumbs down feedback")
        return data


class MessageFeedbackResponse(BaseModel):
    id: str
    message_id: str
    user_id: str
    rating: str
    model_provider: str | None
    model_name: str | None
    time_saved_minutes: int | None
    improvement_notes: str | None
    issue_description: str | None
    time_spent_minutes: int | None
    created_at: datetime
    updated_at: datetime
    conversation_requires_feedback: bool = False

    model_config = ConfigDict(from_attributes=True)


class MessageFeedbackDeleteResponse(BaseModel):
    conversation_requires_feedback: bool = False
