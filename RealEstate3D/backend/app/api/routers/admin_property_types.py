from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_current_admin,
    get_property_type_service,
)
from app.models.property_type import PropertyType
from app.schemas.property_type import (
    PropertyTypeCreate,
    PropertyTypeSchema,
    PropertyTypeUpdate,
)
from app.services.property_type import (
    PropertyTypeAlreadyExistsError,
    PropertyTypeInUseError,
    PropertyTypeNotFoundError,
    PropertyTypeService,
)

router = APIRouter(
    prefix="/admin/property-types",
    tags=["Admin - Property Types"],
    dependencies=[Depends(get_current_admin)],
)


@router.post(
    "/",
    response_model=PropertyTypeSchema,
    status_code=status.HTTP_201_CREATED,
)
def create_property_type(
    data: PropertyTypeCreate,
    service: PropertyTypeService = Depends(get_property_type_service),
) -> PropertyType:
    try:
        return service.create(data)
    except PropertyTypeAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.patch(
    "/{property_type_id}",
    response_model=PropertyTypeSchema,
)
def update_property_type(
    property_type_id: str,
    data: PropertyTypeUpdate,
    service: PropertyTypeService = Depends(get_property_type_service),
) -> PropertyType:
    try:
        return service.update(property_type_id, data)
    except PropertyTypeNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except PropertyTypeAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.delete(
    "/{property_type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_property_type(
    property_type_id: str,
    service: PropertyTypeService = Depends(get_property_type_service),
) -> None:
    try:
        service.delete(property_type_id)
    except PropertyTypeNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except PropertyTypeInUseError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
