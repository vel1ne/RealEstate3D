from pydantic import BaseModel, ConfigDict


class PropertyFilterSchema(BaseModel):
    id: str
    name: str
    slug: str
    filter_type: str
    is_required: bool

    model_config = ConfigDict(from_attributes=True)