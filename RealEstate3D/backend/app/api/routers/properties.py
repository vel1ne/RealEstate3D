
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.property import PropertyCreate, PropertySchema, PropertyUpdate
from app.services.property import PropertyNotFoundError, PropertyService
from app.services.property_type import PropertyTypeNotFoundError

router = APIRouter(prefix="/properties", tags=["Properties"])


@router.get("/", response_model=list[PropertySchema])
def get_properties(db: Session = Depends(get_db)):
    service = PropertyService(db)
    return service.get_all_properties()


@router.get("/{property_id}", response_model=PropertySchema)
def get_property(property_id: str, db: Session = Depends(get_db)):
    service = PropertyService(db)

    try:
        return service.get_property(property_id)
    except PropertyNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.post(
    "/",
    response_model=PropertySchema,
    status_code=status.HTTP_201_CREATED,
)
def create_property(data: PropertyCreate, db: Session = Depends(get_db)):
    service = PropertyService(db)

    try:
        return service.create_property(data)
    except PropertyTypeNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.patch("/{property_id}", response_model=PropertySchema)
def update_property(
    property_id: str,
    data: PropertyUpdate,
    db: Session = Depends(get_db),
):
    service = PropertyService(db)

    try:
        return service.update_property(property_id, data)
    except PropertyNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(property_id: str, db: Session = Depends(get_db)):
    service = PropertyService(db)

    try:
        service.delete_property(property_id)
    except PropertyNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
