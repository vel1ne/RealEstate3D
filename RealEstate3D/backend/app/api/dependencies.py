from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.property_filter import PropertyFilterRepository
from app.repositories.property_type import PropertyTypeRepository
from app.services.property_filter import PropertyFilterService
from app.services.property_type import PropertyTypeService


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_admin():
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access is required",
    )


def get_property_type_service(
    db: Session = Depends(get_db),
) -> PropertyTypeService:
    repository = PropertyTypeRepository(db)
    return PropertyTypeService(repository)


def get_property_filter_service(
    db: Session = Depends(get_db),
) -> PropertyFilterService:
    filter_repository = PropertyFilterRepository(db)
    type_repository = PropertyTypeRepository(db)

    return PropertyFilterService(
        filter_repository=filter_repository,
        type_repository=type_repository,
    )
