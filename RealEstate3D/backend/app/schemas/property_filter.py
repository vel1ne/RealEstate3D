from pydantic import BaseModel, ConfigDict, Field, field_validator


class PropertyFilterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=100)
    filter_type: str = Field(min_length=1, max_length=50)
    is_required: bool = False
    property_type_id: str


class PropertyFilterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    filter_type: str | None = Field(default=None, min_length=1, max_length=50)
    is_required: bool | None = None

    @field_validator("name", "slug", "filter_type", "is_required", mode="before")
    @classmethod
    def validate_not_null(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class PropertyFilterSchema(BaseModel):
    id: str
    name: str
    slug: str
    filter_type: str
    is_required: bool
    property_type_id: str

    model_config = ConfigDict(from_attributes=True)
