from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_current_admin,
    get_property_filter_service,
)
from app.models.property_filter import PropertyFilter
from app.schemas.property_filter import (
    PropertyFilterCreate,
    PropertyFilterSchema,
    PropertyFilterUpdate,
)
from app.services.property_filter import (
    PropertyFilterAlreadyExistsError,
    PropertyFilterInUseError,
    PropertyFilterNotFoundError,
    PropertyFilterService,
    PropertyTypeNotFoundError,
)

router = APIRouter(
    prefix="/admin/property-filters",
    tags=["Admin - Property Filters"],
    dependencies=[Depends(get_current_admin)],
)


@router.post(
    "/",
    response_model=PropertyFilterSchema,
    status_code=status.HTTP_201_CREATED,
)
def create_property_filter(
    data: PropertyFilterCreate,
    service: PropertyFilterService = Depends(get_property_filter_service),
) -> PropertyFilter:
    try:
        return service.create(data)
    except PropertyTypeNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except PropertyFilterAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.patch(
    "/{filter_id}",
    response_model=PropertyFilterSchema,
)
def update_property_filter(
    filter_id: str,
    data: PropertyFilterUpdate,
    service: PropertyFilterService = Depends(get_property_filter_service),
) -> PropertyFilter:
    try:
        return service.update(filter_id, data)
    except PropertyFilterNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except PropertyFilterAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.delete(
    "/{filter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_property_filter(
    filter_id: str,
    service: PropertyFilterService = Depends(get_property_filter_service),
) -> None:
    try:
        service.delete(filter_id)
    except PropertyFilterNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except PropertyFilterInUseError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
