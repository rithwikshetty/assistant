from typing import Literal, Optional
from pydantic import BaseModel, Field

ProviderLiteral = Literal["openai"]


class ChatProviderResponse(BaseModel):
    provider: ProviderLiteral
    # Default-tier model
    default_model: str
    # Power-tier model
    power_model: str
    available_models: list[str]


class ChatProviderUpdate(BaseModel):
    default_model: Optional[str] = Field(None, description="Model for default-tier users")
    power_model: Optional[str] = Field(None, description="Model for power-tier users")
