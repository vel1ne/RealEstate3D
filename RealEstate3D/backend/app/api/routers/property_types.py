from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_property_type_service
from app.schemas.property_filter import PropertyFilterSchema
from app.schemas.property_type import PropertyTypeSchema
from app.services.property_type import (
    PropertyTypeNotFoundError,
    PropertyTypeService,
)

router = APIRouter(prefix="/property-types", tags=["Property Types"])


@router.get("/", response_model=list[PropertyTypeSchema])
def get_property_types(
    service: PropertyTypeService = Depends(get_property_type_service),
):
    return service.get_all()


@router.get(
    "/{slug}/filters",
    response_model=list[PropertyFilterSchema],
)
def get_property_type_filters(
    slug: str,
    service: PropertyTypeService = Depends(get_property_type_service),
):
    try:
        property_type = service.get_by_slug(slug)
    except PropertyTypeNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return property_type.filters
