"""ORM models: catalogue, PostGIS warehouses, demand history, agent runs."""
import uuid
from datetime import datetime, timezone

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def money() -> Numeric:
    return Numeric(12, 2, asdecimal=False)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), index=True)
    cost: Mapped[float] = mapped_column(money())
    current_price: Mapped[float] = mapped_column(money())
    map_price: Mapped[float | None] = mapped_column(money(), nullable=True)  # minimum advertised price
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    location = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    capacity_units: Mapped[int] = mapped_column(Integer, default=10_000)


class InventoryLevel(Base):
    __tablename__ = "inventory_levels"
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_wh"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"), index=True)
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    lead_time_days: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False), default=4.0)


class PricePoint(Base):
    """Daily observed (price, units) pairs used to estimate price elasticity."""
    __tablename__ = "price_points"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    price: Mapped[float] = mapped_column(money())
    units_sold: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CompetitorSignal(Base):
    __tablename__ = "competitor_signals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    competitor: Mapped[str] = mapped_column(String(120))
    price: Mapped[float] = mapped_column(money())
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    request: Mapped[dict] = mapped_column(JSONB, default=dict)
    trace: Mapped[list] = mapped_column(JSONB, default=list)
    decision: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VisionAnalysis(Base):
    __tablename__ = "vision_analyses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
