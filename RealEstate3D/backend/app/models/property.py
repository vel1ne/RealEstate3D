from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    property_type: Mapped[str] = mapped_column(String(100), nullable=False)

    area: Mapped[float] = mapped_column(Float, nullable=False)
    monthly_rent: Mapped[float] = mapped_column(Float, nullable=False)

    ceiling_height: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    floor_load: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    power_kw: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    truck_access: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
