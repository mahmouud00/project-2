"""Field work: maintenance requests, technician jobs (survey / installation / maintenance visits)
and the GPS points a technician's phone sends while on a job."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, IdMixin, SoftDeleteMixin, TenantMixin, utcnow

JOB_KINDS = ("survey", "installation", "maintenance")
JOB_STATUSES = ("scheduled", "on_way", "arrived", "done", "cancelled")
MAINTENANCE_STATUSES = ("open", "scheduled", "done", "cancelled")


class MaintenanceRequest(Base, Entity, SoftDeleteMixin):
    """طلب صيانة from a customer (often for a unit the factory installed)."""
    __tablename__ = "maintenance_requests"
    __table_args__ = (UniqueConstraint("company_id", "number"),)
    __pii__ = ("address", "location_url", "latitude", "longitude")

    number: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_orders.id"),
                                                            nullable=True)
    request_date: Mapped[date] = mapped_column(Date, default=date.today)
    description: Mapped[str] = mapped_column(Text, default="")
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    notes: Mapped[str] = mapped_column(Text, default="")


class FieldJob(Base, Entity, SoftDeleteMixin):
    """A visit assigned to a technician: survey, installation or maintenance."""
    __tablename__ = "field_jobs"
    __pii__ = ("address", "location_url", "latitude", "longitude")

    kind: Mapped[str] = mapped_column(String(20))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    survey_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("site_surveys.id"), nullable=True)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_orders.id"),
                                                            nullable=True)
    maintenance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("maintenance_requests.id"),
                                                             nullable=True)
    technician_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    result_note: Mapped[str] = mapped_column(Text, default="")


class TechnicianLocation(Base, IdMixin, TenantMixin):
    """GPS point from a technician's phone, sent only while one of their jobs is on the way / arrived.
    Personal data: erased after LOCATION_RETENTION_DAYS; reading it is logged in pii_access_log."""
    __tablename__ = "technician_locations"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("field_jobs.id", ondelete="SET NULL"),
                                                     nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 1), nullable=True)
