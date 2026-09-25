from datetime import datetime

from pydantic import BaseModel, Field

from api.config import MAX_RATE_LIMIT_PER_MINUTE


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(default="default", max_length=200)
    # Omit to use DEFAULT_RATE_LIMIT_PER_MINUTE. Different internal apps
    # have different needs (an interactive tool vs. a batch job), so any
    # key can request its own limit up to MAX_RATE_LIMIT_PER_MINUTE.
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=MAX_RATE_LIMIT_PER_MINUTE)


class ApiKeyUpdateRequest(BaseModel):
    rate_limit_per_minute: int = Field(ge=1, le=MAX_RATE_LIMIT_PER_MINUTE)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    rate_limit_per_minute: int
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyCreatedOut(ApiKeyOut):
    # Only present on the create response — the raw key is never stored and
    # can't be retrieved again after this.
    key: str
