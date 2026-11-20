from pydantic import BaseModel, ConfigDict, Field


class PropertyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    address: str = Field(min_length=1, max_length=500)
    property_type_id: str


class PropertyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    address: str | None = Field(default=None, min_length=1, max_length=500)


class PropertySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    address: str
    property_type_id: str
