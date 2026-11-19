from pydantic import BaseModel, ConfigDict, Field, field_validator


class PropertyTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=100)
    description: str | None = None


class PropertyTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None

    @field_validator("name", "slug", mode="before")
    @classmethod
    def validate_required_fields(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class PropertyTypeSchema(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None

    model_config = ConfigDict(from_attributes=True)
