from uuid import uuid4
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.property import Property
    from app.models.property_filter import PropertyFilter


class PropertyType(Base):
    __tablename__ = "property_types"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    properties: Mapped[list["Property"]] = relationship(
        back_populates="property_type",
    )
    filters: Mapped[list["PropertyFilter"]] = relationship(
        back_populates="property_type",
    )