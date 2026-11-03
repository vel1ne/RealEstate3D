from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PropertyBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    address: str = Field(min_length=1, max_length=500)
    property_type: str = Field(min_length=1, max_length=100)

    area: float = Field(gt=0)
    monthly_rent: float = Field(ge=0)

    ceiling_height: float | None = Field(default=None, gt=0)
    floor_load: float | None = Field(default=None, gt=0)
    power_kw: float | None = Field(default=None, ge=0)

    truck_access: bool = False
    description: str | None = None


class PropertyCreate(PropertyBase):
    pass


class PropertyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    property_type: str | None = Field(default=None, min_length=1, max_length=100)

    area: float | None = Field(default=None, gt=0)
    monthly_rent: float | None = Field(default=None, ge=0)

    ceiling_height: float | None = Field(default=None, gt=0)
    floor_load: float | None = Field(default=None, gt=0)
    power_kw: float | None = Field(default=None, ge=0)

    truck_access: bool | None = None
    description: str | None = None


class PropertyRead(PropertyBase):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
