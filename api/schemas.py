"""
Pydantic schemas for request validation and API response serialisation.

Naming convention:
  <Model>Create  – request body when creating a resource
  <Model>Update  – request body for partial updates
  <Model>        – full response (includes server-set fields like id, created_at)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from api.models import (
    GeneratorType,
    ListingStatus,
    MaterialType,
    PickupStatus,
    ProcessorType,
    QualityGrade,
    RecommendedBy,
)


# ── Shared config ─────────────────────────────────────────────────────────────

class _Base(BaseModel):
    model_config = {"from_attributes": True}


# ── Generator ─────────────────────────────────────────────────────────────────

class GeneratorCreate(BaseModel):
    model_config = {"extra": "forbid"}
    name:          str          = Field(..., min_length=2, max_length=200)
    type:          GeneratorType
    address:       str          = Field(..., min_length=5)
    pincode:       str          = Field(..., pattern=r"^\d{6}$")
    lat:           float        = Field(..., ge=-90, le=90)
    lng:           float        = Field(..., ge=-180, le=180)
    contact_email: str
    is_synthetic:  bool         = False


class Generator(_Base):
    id:            int
    name:          str
    type:          GeneratorType
    address:       str
    pincode:       str
    lat:           float
    lng:           float
    contact_email: str
    registered_at: datetime
    is_synthetic:  bool


# ── WasteListing ──────────────────────────────────────────────────────────────

class WasteListingCreate(BaseModel):
    model_config = {"extra": "forbid"}
    generator_id:    int
    material_type:   MaterialType
    quantity_kg:     float        = Field(..., gt=0)
    quality_grade:   QualityGrade
    available_from:  date
    available_until: date
    description:     Optional[str] = None
    is_synthetic:    bool          = False

    @field_validator("available_until")
    @classmethod
    def until_after_from(cls, v: date, info: Any) -> date:
        from_date = info.data.get("available_from")
        if from_date and v < from_date:
            raise ValueError("available_until must be on or after available_from")
        return v


class WasteListingUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    status: ListingStatus


class WasteListing(_Base):
    id:              int
    generator_id:    int
    material_type:   MaterialType
    quantity_kg:     float
    quality_grade:   QualityGrade
    available_from:  date
    available_until: date
    description:     Optional[str]
    status:          ListingStatus
    created_at:      datetime
    is_synthetic:    bool


# ── Processor ─────────────────────────────────────────────────────────────────

class ProcessorCreate(BaseModel):
    model_config = {"extra": "forbid"}
    name:           str          = Field(..., min_length=2, max_length=200)
    processor_type: ProcessorType
    address:        str          = Field(..., min_length=5)
    pincode:        str          = Field(..., pattern=r"^\d{6}$")
    lat:            float        = Field(..., ge=-90, le=90)
    lng:            float        = Field(..., ge=-180, le=180)
    contact_email:  str
    licence_number: str          = Field(..., min_length=3)
    is_synthetic:   bool         = False


class Processor(_Base):
    id:             int
    name:           str
    processor_type: ProcessorType
    address:        str
    pincode:        str
    lat:            float
    lng:            float
    contact_email:  str
    licence_number: str
    registered_at:  datetime
    is_synthetic:   bool


# ── ProcessorCapacity ─────────────────────────────────────────────────────────

class ProcessorCapacityCreate(BaseModel):
    model_config = {"extra": "forbid"}
    processor_id:    int
    material_type:   MaterialType
    min_quantity_kg: float = Field(..., ge=0)
    max_quantity_kg: float = Field(..., gt=0)
    accepted_grades: str   = Field(..., pattern=r"^[ABC](,[ABC])*$",
                                   description="Comma-separated grades, e.g. 'A,B'")
    available_from:  date
    available_until: date

    @field_validator("max_quantity_kg")
    @classmethod
    def max_gt_min(cls, v: float, info: Any) -> float:
        min_qty = info.data.get("min_quantity_kg")
        if min_qty is not None and v <= min_qty:
            raise ValueError("max_quantity_kg must be greater than min_quantity_kg")
        return v


class ProcessorCapacity(_Base):
    id:              int
    processor_id:    int
    material_type:   MaterialType
    min_quantity_kg: float
    max_quantity_kg: float
    accepted_grades: str
    available_from:  date
    available_until: date
    current_load_kg: float


# ── Match / Score breakdown ───────────────────────────────────────────────────

class ScoreBreakdown(BaseModel):
    material_score:     float = Field(..., description="1.0 if material accepted, else 0 (hard filter)")
    quantity_score:     float = Field(..., ge=0, le=1)
    quality_score:      float = Field(..., ge=0, le=1)
    distance_score:     float = Field(..., ge=0, le=1)
    distance_km:        float
    availability_score: float = Field(..., ge=0, le=1)
    composite_score:    float = Field(..., ge=0, le=1)


class MatchResult(BaseModel):
    processor_id:    int
    processor_name:  str
    processor_type:  ProcessorType
    score:           float
    score_breakdown: ScoreBreakdown
    explanation:     str
    is_synthetic:    bool


class MatchResponse(BaseModel):
    listing_id:  int
    top_matches: List[MatchResult]
    total_candidates_evaluated: int


# ── Pickup ────────────────────────────────────────────────────────────────────

class PickupCreate(BaseModel):
    model_config = {"extra": "forbid"}
    listing_id:    int
    processor_id:  int
    proposed_date: date
    match_id:      Optional[int] = None
    notes:         Optional[str] = None


class PickupStatusUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    status:      PickupStatus
    approved_by: Optional[str] = None
    notes:       Optional[str] = None


class Pickup(_Base):
    id:            int
    match_id:      Optional[int]
    listing_id:    int
    processor_id:  int
    proposed_date: date
    approved_by:   Optional[str]
    approved_at:   Optional[datetime]
    status:        PickupStatus
    co2_kg_saved:  Optional[float]
    notes:         Optional[str]
    created_at:    datetime


# ── Agent ─────────────────────────────────────────────────────────────────────

class AgentRunRequest(BaseModel):
    model_config = {"extra": "forbid"}
    listing_id:   int
    user_message: Optional[str] = "Find the best processors for this waste listing."


class AgentResponse(BaseModel):
    session_id:        str
    narrative:         str
    top_matches:       List[MatchResult]
    proposed_pickup:   Optional[Dict[str, Any]] = None
    requires_approval: bool = True
    mock:              bool = False  # True when USE_MOCK_AGENT=true
