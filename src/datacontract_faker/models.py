"""Internal domain models that decouple the generation engine from the ODCS wire format."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OutputFormat(str, Enum):
    CSV = "csv"
    JSON = "json"
    JSONL = "jsonl"
    PARQUET = "parquet"


@dataclass
class QualityRule:
    """Metadata from a DataQuality entry — informational only for the generator."""
    type: str          # text | library | sql | custom
    metric: str | None = None   # nullValues | rowCount | invalidValues | …
    operator: str | None = None # mustBe | mustBeBetween | mustBeGreaterThan | …
    value: Any = None


@dataclass
class FieldSpec:
    name: str
    # ODCS v3.1.0 canonical logicalType: string|date|timestamp|time|number|integer|object|array|boolean
    logical_type: str | None = None
    # Storage / vendor type (free-form string, e.g. "decimal", "varchar(255)")
    physical_type: str | None = None
    # String format hint: email | uuid | uri | ipv4 | ipv6 | hostname | password | byte | binary
    format_hint: str | None = None
    required: bool = True
    # primaryKey implies uniqueness; stored separately to preserve the original contract intent
    primary_key: bool = False
    unique: bool = False
    # Probability of None when required=False
    nullable_ratio: float = 0.0
    # Value bounds — sourced from field-level minimum/maximum in ODCS v3.1.0
    minimum: Any = None
    maximum: Any = None
    # Strict (open-interval) bounds: value must be > exclusiveMinimum and < exclusiveMaximum
    exclusive_minimum: Any = None
    exclusive_maximum: Any = None
    # Generated value must be a multiple of this (numeric)
    multiple_of: Any = None
    # String length bounds
    min_length: int | None = None
    max_length: int | None = None
    # ODCS examples array — used as a closed pick-list during generation
    examples: list[Any] | None = None
    # ODCS pattern (regex) — used to generate conforming strings
    pattern: str | None = None
    # Quality metadata (parsed but does not drive generation directly)
    quality_rules: list[QualityRule] = field(default_factory=list)
    # Nested object: populated when logicalType=object and properties are present
    nested_fields: list["FieldSpec"] = field(default_factory=list)
    # Array item schema: populated when logicalType=array and items are present
    items_spec: "FieldSpec | None" = None
    # Array cardinality bounds from ODCS minItems/maxItems
    min_items: int = 0
    max_items: int = 5
    # Whether array items must be unique
    unique_items: bool = False

    @property
    def effective_type(self) -> str | None:
        """Logical type is the canonical descriptor; physical type is the fallback."""
        return self.logical_type or self.physical_type


@dataclass
class ModelSpec:
    name: str
    fields: list[FieldSpec] = field(default_factory=list)


@dataclass
class RelationshipSpec:
    type: str  # "foreignKey"
    from_model: str
    from_field: str
    to_model: str
    to_field: str


@dataclass
class GenerationSchema:
    contract_id: str
    contract_version: str
    models: dict[str, ModelSpec] = field(default_factory=dict)
    relationships: list[RelationshipSpec] = field(default_factory=list)
