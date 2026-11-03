from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.schemas.property import PropertyCreate, PropertyRead, PropertyUpdate
from app.services.property import PropertyNotFoundError, PropertyService


router = APIRouter(
    prefix="/properties",
    tags=["Properties"],
)


@router.get("/", response_model=list[PropertyRead])
def get_properties(
    db: Session = Depends(get_db),
) -> list[PropertyRead]:
    service = PropertyService(db)
    return service.get_all_properties()


@router.get("/{property_id}", response_model=PropertyRead)
def get_property(
    property_id: str,
    db: Session = Depends(get_db),
) -> PropertyRead:
    service = PropertyService(db)

    try:
        return service.get_property(property_id)
    except PropertyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/",
    response_model=PropertyRead,
    status_code=status.HTTP_201_CREATED,
)
def create_property(
    data: PropertyCreate,
    db: Session = Depends(get_db),
) -> PropertyRead:
    service = PropertyService(db)
    return service.create_property(data)


@router.patch("/{property_id}", response_model=PropertyRead)
def update_property(
    property_id: str,
    data: PropertyUpdate,
    db: Session = Depends(get_db),
) -> PropertyRead:
    service = PropertyService(db)

    try:
        return service.update_property(property_id, data)
    except PropertyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{property_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_property(
    property_id: str,
    db: Session = Depends(get_db),
) -> Response:
    service = PropertyService(db)

    try:
        service.delete_property(property_id)
    except PropertyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
