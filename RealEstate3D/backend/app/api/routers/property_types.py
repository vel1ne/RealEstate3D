from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.repositories.property_type import PropertyTypeRepository
from app.schemas.property_filter import PropertyFilterSchema
from app.schemas.property_type import PropertyTypeSchema

router = APIRouter(prefix="/property-types", tags=["Property Types"])


@router.get("/", response_model=list[PropertyTypeSchema])
def get_property_types(db: Session = Depends(get_db)):
    repository = PropertyTypeRepository(db)
    return repository.get_all()


@router.get(
    "/{slug}/filters",
    response_model=list[PropertyFilterSchema],
)
def get_property_type_filters(
    slug: str,
    db: Session = Depends(get_db),
):
    repository = PropertyTypeRepository(db)
    property_type = repository.get_by_slug(slug)

    if property_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property type not found",
        )

    return property_type.filters