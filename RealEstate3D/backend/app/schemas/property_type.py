from pydantic import BaseModel, ConfigDict


class PropertyTypeSchema(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None

    model_config = ConfigDict(from_attributes=True)