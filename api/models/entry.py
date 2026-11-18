from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EntryCreate(BaseModel):
    """Model for creating a new journal entry (user input)."""
    work: str = Field(
        max_length=256,
        description="What did you work on today?",
        json_schema_extra={"example": "Studied FastAPI and built my first API endpoints"}
    )
    struggle: str = Field(
        max_length=256,
        description="What's one thing you struggled with today?",
        json_schema_extra={"example": "Understanding async/await syntax and when to use it"}
    )
    intention: str = Field(
        max_length=256,
        description="What will you study/work on tomorrow?",
        json_schema_extra={"example": "Practice PostgreSQL queries and database design"}
    )
    
    @field_validator('work', 'struggle', 'intention')
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure fields are not empty or just whitespace."""
        if not v or not v.strip():
            raise ValueError('Field cannot be empty or contain only whitespace')
        return v.strip()
    
    @field_validator('work', 'struggle', 'intention')
    @classmethod
    def validate_min_length(cls, v: str) -> str:
        """Ensure fields have at least 3 characters."""
        if len(v.strip()) < 3:
            raise ValueError('Field must be at least 3 characters long')
        return v

class Entry(BaseModel):
    """Full entry model with validation rules and auto-generated fields."""
    
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for the entry (UUID)."
    )
    work: str = Field(
        ...,
        max_length=256,
        description="What did you work on today?"
    )
    struggle: str = Field(
        ...,
        max_length=256,
        description="What's one thing you struggled with today?"
    )
    intention: str = Field(
        ...,
        max_length=256,
        description="What will you study/work on tomorrow?"
    )
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the entry was created."
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the entry was last updated."
    )
    
    @field_validator('work', 'struggle', 'intention')
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure fields are not empty or just whitespace."""
        if not v or not v.strip():
            raise ValueError('Field cannot be empty or contain only whitespace')
        return v.strip()
    
    @field_validator('work', 'struggle', 'intention')
    @classmethod
    def validate_min_length(cls, v: str) -> str:
        """Ensure fields have at least 3 characters."""
        if len(v.strip()) < 3:
            raise ValueError('Field must be at least 3 characters long')
        return v

class EntryUpdate(BaseModel):
    """Validate partial updates to a journal entry."""

    model_config = ConfigDict(extra="forbid")

    work: str | None = Field(default=None, max_length=256)
    struggle: str | None = Field(default=None, max_length=256)
    intention: str | None = Field(default=None, max_length=256)

    @field_validator("work", "struggle", "intention")
    @classmethod
    def validate_field(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Field cannot be null")

        value = value.strip()

        if len(value) < 3:
            raise ValueError("Field must contain at least 3 characters")

        return value

    @model_validator(mode="after")
    def validate_not_empty(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")

        return self
