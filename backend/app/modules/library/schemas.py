from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.api.common import ORMModel, Record, VersionedUpdate

IDENT = re.compile(r"^[^\W\d]\w*$", re.UNICODE)
Status = Literal["approved", "trial"]


def _ident(v: str) -> str:
    if not IDENT.match(v):
        raise ValueError("must be an identifier (letters, digits, underscore; not starting with a digit)")
    return v


# ---------------------------------------------------------------- colours / media
class ColorIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str
    hex: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


class ColorUpdate(VersionedUpdate):
    name: str | None = None
    hex: str | None = None
    is_active: bool | None = None


class ColorOut(Record):
    code: str
    name: str
    hex: str | None
    is_active: bool
    company_id: uuid.UUID


class MediaOut(ORMModel):
    id: uuid.UUID
    sha256: str
    mime: str
    filename: str
    size: int
    url: str = ""


# ---------------------------------------------------------------- systems
class SystemIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str
    supplier: str = ""
    material_type: Literal["upvc", "shutter", "aluminum"]
    unit: Literal["mm", "cm"] = "mm"
    rounding_step_mm: Decimal = Decimal("0")
    rounding_mode: Literal["half_up", "up", "down"] = "half_up"
    status: Status = "trial"
    description: str = ""
    image_id: uuid.UUID | None = None


class SystemUpdate(VersionedUpdate):
    name: str | None = None
    supplier: str | None = None
    unit: Literal["mm", "cm"] | None = None
    rounding_step_mm: Decimal | None = None
    rounding_mode: Literal["half_up", "up", "down"] | None = None
    status: Status | None = None
    description: str | None = None
    image_id: uuid.UUID | None = None
    is_active: bool | None = None


class SystemOut(Record):
    company_id: uuid.UUID
    code: str
    name: str
    supplier: str
    material_type: str
    unit: str
    rounding_step_mm: Decimal
    rounding_mode: str
    status: str
    description: str
    image_id: uuid.UUID | None
    is_active: bool
    current_version_id: uuid.UUID | None
    is_library: bool = False


class ConstantIn(BaseModel):
    name: str = Field(max_length=80)
    label: str = ""
    value: Decimal
    unit: str = ""
    description: str = ""
    sort: int = 0
    _n = field_validator("name")(_ident)


class ConstantUpdate(VersionedUpdate):
    label: str | None = None
    value: Decimal | None = None
    unit: str | None = None
    description: str | None = None
    sort: int | None = None


class ConstantOut(Record):
    system_id: uuid.UUID
    name: str
    label: str
    value: Decimal
    unit: str
    description: str
    sort: int


# ---------------------------------------------------------------- materials
class VariantIn(BaseModel):
    color_code: str
    sku: str = Field(min_length=1, max_length=80)
    name: str = ""
    reference_cost: Decimal | None = None
    is_active: bool = True


class VariantOut(ORMModel):
    id: uuid.UUID
    color_code: str
    sku: str
    name: str
    reference_cost: Decimal | None
    is_active: bool


class MaterialIn(BaseModel):
    system_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=60)
    name: str
    category: str = ""
    kind: Literal["profile", "reinforcement", "accessory", "glass", "gasket", "consumable", "panel", "other"] = "profile"
    unit: Literal["m", "pcs", "set", "roll", "m2", "kg", "l"] = "m"
    bar_length_mm: Decimal | None = None
    min_piece_mm: Decimal | None = None
    weight_kg_per_m: Decimal | None = None
    reference_cost: Decimal | None = None
    image_id: uuid.UUID | None = None
    status: Status = "approved"
    variants: list[VariantIn] = []


class MaterialUpdate(VersionedUpdate):
    system_id: uuid.UUID | None = None
    name: str | None = None
    category: str | None = None
    kind: Literal["profile", "reinforcement", "accessory", "glass", "gasket", "consumable", "panel", "other"] | None = None
    unit: Literal["m", "pcs", "set", "roll", "m2", "kg", "l"] | None = None
    bar_length_mm: Decimal | None = None
    min_piece_mm: Decimal | None = None
    weight_kg_per_m: Decimal | None = None
    reference_cost: Decimal | None = None
    image_id: uuid.UUID | None = None
    status: Status | None = None
    is_active: bool | None = None
    variants: list[VariantIn] | None = None


class MaterialOut(Record):
    company_id: uuid.UUID
    system_id: uuid.UUID | None
    code: str
    name: str
    category: str
    kind: str
    unit: str
    bar_length_mm: Decimal | None
    min_piece_mm: Decimal | None
    weight_kg_per_m: Decimal | None
    reference_cost: Decimal | None
    image_id: uuid.UUID | None
    status: str
    is_active: bool
    variants: list[VariantOut] = []


# ---------------------------------------------------------------- model definition
class Choice(BaseModel):
    value: Decimal
    label: str


class Param(BaseModel):
    name: str
    label: str = ""
    type: Literal["number", "length", "int", "count", "choice", "bool"] = "number"
    default: Decimal | bool | None = None
    min: Decimal | None = None
    max: Decimal | None = None
    choices: list[Choice] = []
    _n = field_validator("name")(_ident)


class Formula(BaseModel):
    key: str
    label: str = ""
    expr: str
    unit: Literal["length", "count", "area_m2", "number"] = "length"
    _n = field_validator("key")(_ident)


class Piece(BaseModel):
    """One cut piece: which material, its length (deduction formula), count and angles."""
    key: str
    label: str = ""
    role: str | None = None  # frame | sash | mullion | bead | reinforcement | screen | track | ...
    # Element the piece belongs to (e.g. "حلق", "ضلفة", "باكتة") and which side it is cut for,
    # so screens can show every element's width and height deductions together (width first).
    element: str | None = None
    side: Literal["width", "height"] | None = None
    material_code: str
    length_expr: str
    qty_expr: str = "1"
    angle_left: str = "90"
    angle_right: str = "90"
    condition: str | None = None
    _n = field_validator("key")(_ident)


class Glass(BaseModel):
    key: str
    label: str = ""
    material_code: str | None = None
    width_expr: str
    height_expr: str
    qty_expr: str = "1"
    condition: str | None = None
    _n = field_validator("key")(_ident)


class Accessory(BaseModel):
    key: str
    label: str = ""
    material_code: str
    qty_expr: str
    condition: str | None = None
    _n = field_validator("key")(_ident)


class Rule(BaseModel):
    expr: str
    level: Literal["error", "warning"] = "error"
    code: str = "RULE_FAILED"
    message: str = ""


class DrawingElement(BaseModel):
    type: str = "rect"  # frame | sash | glass | mullion | panel | screen | rect
    label: str | None = None
    opening: str | None = None  # fixed | sliding_left | sliding_right | casement_left | casement_right | tilt | tilt_turn
    x: str = "0"
    y: str = "0"
    w: str
    h: str
    condition: str | None = None


class Definition(BaseModel):
    params: list[Param] = []
    formulas: list[Formula] = []
    pieces: list[Piece] = []
    glass: list[Glass] = []
    accessories: list[Accessory] = []
    validations: list[Rule] = []
    drawing: list[DrawingElement] = []


class ModelIn(BaseModel):
    system_id: uuid.UUID
    code: str = Field(min_length=1, max_length=60)
    name: str
    category: str = "window"
    description: str = ""
    image_id: uuid.UUID | None = None
    status: Status = "trial"
    sort: int = 0
    definition: Definition = Definition()


class ModelUpdate(VersionedUpdate):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    image_id: uuid.UUID | None = None
    status: Status | None = None
    sort: int | None = None
    is_active: bool | None = None
    definition: Definition | None = None


class ModelOut(Record):
    company_id: uuid.UUID
    system_id: uuid.UUID
    code: str
    name: str
    category: str
    description: str
    image_id: uuid.UUID | None
    status: str
    sort: int
    is_active: bool
    definition: dict


class TestCaseIn(BaseModel):
    name: str = ""
    opening_width_mm: Decimal
    opening_height_mm: Decimal
    params: dict = {}
    expected: dict


class TestCaseOut(Record):
    model_id: uuid.UUID
    name: str
    opening_width_mm: Decimal
    opening_height_mm: Decimal
    params: dict
    expected: dict


class VersionOut(ORMModel):
    id: uuid.UUID
    system_id: uuid.UUID
    version_no: int
    sha256: str
    notes: str
    published_at: datetime


class PublishIn(BaseModel):
    notes: str = ""


# ---------------------------------------------------------------- company adjustments
class CalibrationItem(BaseModel):
    constant_name: str
    delta: Decimal
    note: str = ""


class OverrideItem(BaseModel):
    constant_name: str
    value: Decimal
    note: str = ""


class SystemAdjustments(BaseModel):
    calibrations: list[CalibrationItem] = []
    overrides: list[OverrideItem] = []


class MaterialSettingIn(BaseModel):
    color_code: str = ""
    unit_cost: Decimal | None = None
    internal_code: str | None = None
    is_hidden: bool = False


# ---------------------------------------------------------------- calculation
class CalculateIn(BaseModel):
    model_id: uuid.UUID
    opening_width_mm: Decimal = Field(gt=0)
    opening_height_mm: Decimal = Field(gt=0)
    params: dict = {}
    version_id: uuid.UUID | None = None  # default: current published version
