"""ContractParser: loads, validates, and converts an ODCS v3.1.0 contract into a GenerationSchema.

ODCS v3.1.0 wire format recap
------------------------------
- Top level: version, apiVersion, kind, id, status (all required); no "info" object.
- Schema list: ``schema:`` array; each item is a SchemaObject with ``name:`` and ``properties:`` array.
- Field: each SchemaProperty has ``name:``, ``logicalType:`` (string|date|timestamp|time|number|
  integer|object|array|boolean), optional ``format:`` (email|uuid|uri|ipv4|ipv6|hostname|…),
  ``minimum:``, ``maximum:``, ``required:``, ``unique:``, ``examples:``, ``quality:``.
- Quality rules: ``type: library``, ``metric: rowCount|nullValues|…``, operator (mustBeBetween, …).
  Value ranges are expressed via field-level ``minimum``/``maximum``, NOT quality rules.

Validation delegates to ``datacontract-cli`` so we stay in sync with the official spec.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from .models import FieldSpec, GenerationSchema, ModelSpec, QualityRule, RelationshipSpec

logger = logging.getLogger(__name__)

_MISSING = object()

# Module-level import so tests can patch ``datacontract_faker.parser.DataContract``.
try:
    from datacontract.data_contract import DataContract
except ImportError:
    DataContract = None  # type: ignore[assignment, misc]


class ContractValidationError(Exception):
    """Raised when the data contract fails ODCS linting."""


class ContractParser:
    """Wrap ``datacontract-cli`` to produce a :class:`GenerationSchema`.

    Args:
        nullable_ratio: Probability (0–1) of emitting ``None`` for optional fields.
    """

    def __init__(self, nullable_ratio: float = 0.1) -> None:
        if not 0.0 <= nullable_ratio <= 1.0:
            raise ValueError("nullable_ratio must be in [0, 1]")
        self.nullable_ratio = nullable_ratio

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_and_validate(self, contract_path: Path) -> GenerationSchema:
        """Read *contract_path* from disk, validate it, and return a schema."""
        return self.parse_string(contract_path.read_text(encoding="utf-8"))

    def parse_string(self, contract_str: str) -> GenerationSchema:
        """Parse and validate a raw ODCS YAML/JSON string."""
        if DataContract is None:
            raise ImportError(
                "datacontract-cli is required for contract validation. "
                "Install it with: pip install datacontract-cli"
            )

        dc = DataContract(data_contract_str=contract_str)
        result = dc.lint()
        if getattr(result.result, "value", str(result.result)) in ("failed", "error"):
            failed_checks = [
                c for c in (result.checks or [])
                if getattr(getattr(c, "result", None), "value", "") not in ("passed", "warning")
            ]
            messages = "\n".join(f"  • {c.name}: {getattr(c, 'reason', '')}" for c in failed_checks)
            raise ContractValidationError(
                f"Contract validation failed:\n{messages or 'unknown errors'}"
            )

        # Parse the raw YAML directly — datacontract-cli's internal spec object
        # normalises to its own schema version and drops ODCS v3.1.0 field attributes
        # (format, minimum, maximum, required).  Reading the source YAML preserves them.
        raw: dict[str, Any] = yaml.safe_load(contract_str) or {}
        return self._build_schema(raw)

    # ------------------------------------------------------------------
    # Private translation helpers
    # ------------------------------------------------------------------

    def _build_schema(self, spec: Any) -> GenerationSchema:
        gen_schema = GenerationSchema(
            contract_id=_attr(spec, "id") or "unknown",
            # v3.1.0: version is a top-level string, not nested under info
            contract_version=_attr(spec, "version") or "0.0.0",
        )

        # ODCS v3.1.0 uses ``schema`` (array of SchemaObject).
        # datacontract-cli may expose it as ``schema``, ``schema_``, or ``models`` (legacy).
        schema_list = (
            _attr(spec, "schema")
            or _attr(spec, "schema_")
        )
        models_dict = _attr(spec, "models")

        if schema_list:
            self._parse_schema_list(schema_list, gen_schema)
        elif models_dict:
            # Backward-compat: the CLI may still expose v2-style models dict internally.
            self._parse_models_dict(models_dict, gen_schema)
        else:
            logger.warning("No 'schema' or 'models' section found in contract.")

        self._parse_all_relationships(spec, gen_schema)
        return gen_schema

    def _parse_schema_list(self, schema_list: Any, gen_schema: GenerationSchema) -> None:
        """Handle ODCS v3.1.0: schema is an array of named SchemaObject items."""
        if not hasattr(schema_list, "__iter__"):
            return
        for schema_obj in schema_list:
            model_name = _attr(schema_obj, "name") or "unknown"
            gen_schema.models[model_name] = self._parse_schema_object(model_name, schema_obj)

    def _parse_models_dict(self, models_dict: Any, gen_schema: GenerationSchema) -> None:
        """Handle legacy dict-style models (backward compat with older CLI versions)."""
        if not isinstance(models_dict, dict):
            return
        for name, model_obj in models_dict.items():
            gen_schema.models[name] = self._parse_schema_object(name, model_obj)

    def _parse_schema_object(self, name: str, schema_obj: Any) -> ModelSpec:
        model_spec = ModelSpec(name=name)

        # ODCS v3.1.0: properties is an array of SchemaProperty objects.
        # Backward compat: fields may be a dict (older CLI versions).
        props = _attr(schema_obj, "properties") or _attr(schema_obj, "fields") or []

        if isinstance(props, dict):
            for fname, fobj in props.items():
                model_spec.fields.append(self._parse_field_obj(fname, fobj))
        else:
            for fobj in props:
                fname = _attr(fobj, "name") or "unknown"
                model_spec.fields.append(self._parse_field_obj(fname, fobj))

        return model_spec

    def _parse_field_obj(self, name: str, obj: Any) -> FieldSpec:
        logical_type = _attr(obj, "logicalType") or _attr(obj, "logical_type")
        physical_type = _attr(obj, "physicalType") or _attr(obj, "physical_type")

        # ``format`` is defined per-logicalType in ODCS v3.1.0:
        #   string  → email | uuid | uri | hostname | ipv4 | ipv6 | password | byte | binary
        #   date/timestamp/time → JDK DateTimeFormatter pattern (generation hint only)
        format_hint = _attr(obj, "format") or _attr(obj, "format_hint")

        required = bool(_attr(obj, "required", default=False))
        primary_key = bool(_attr(obj, "primaryKey", default=False))
        unique = bool(_attr(obj, "unique", default=False)) or primary_key

        # Value bounds (ODCS v3.1.0: directly on the field, not inside quality rules)
        minimum = _attr(obj, "minimum")
        maximum = _attr(obj, "maximum")
        exclusive_minimum = _attr(obj, "exclusiveMinimum")
        exclusive_maximum = _attr(obj, "exclusiveMaximum")
        multiple_of = _attr(obj, "multipleOf")

        min_length_raw = _attr(obj, "minLength")
        max_length_raw = _attr(obj, "maxLength")
        min_length = int(min_length_raw) if min_length_raw is not None else None
        max_length = int(max_length_raw) if max_length_raw is not None else None

        examples_raw = _attr(obj, "examples")
        examples = list(examples_raw) if examples_raw else None

        pattern = _attr(obj, "pattern")

        quality_rules = self._parse_quality(_attr(obj, "quality"))

        spec = FieldSpec(
            name=name,
            logical_type=logical_type,
            physical_type=physical_type,
            format_hint=str(format_hint) if format_hint is not None else None,
            required=required,
            primary_key=primary_key,
            unique=unique,
            nullable_ratio=self.nullable_ratio if not required else 0.0,
            minimum=minimum,
            maximum=maximum,
            exclusive_minimum=exclusive_minimum,
            exclusive_maximum=exclusive_maximum,
            multiple_of=multiple_of,
            min_length=min_length,
            max_length=max_length,
            examples=examples,
            pattern=str(pattern) if pattern is not None else None,
            quality_rules=quality_rules,
        )

        norm = (logical_type or "").lower()

        if norm == "object":
            props = _attr(obj, "properties") or []
            if isinstance(props, dict):
                spec.nested_fields = [self._parse_field_obj(k, v) for k, v in props.items()]
            else:
                spec.nested_fields = [
                    self._parse_field_obj(_attr(p, "name") or f"_f{i}", p)
                    for i, p in enumerate(props)
                ]

        elif norm == "array":
            items_raw = _attr(obj, "items")
            if items_raw is not None:
                items_spec = self._parse_field_obj("_item", items_raw)
                # Array items are either present or absent (controlled by array length);
                # they are never individually null.
                items_spec.required = True
                items_spec.nullable_ratio = 0.0
                spec.items_spec = items_spec
            spec.min_items = int(_attr(obj, "minItems", default=0) or 0)
            raw_max = _attr(obj, "maxItems")
            spec.max_items = int(raw_max) if raw_max is not None else 5
            spec.unique_items = bool(_attr(obj, "uniqueItems", default=False))

        return spec

    def _parse_all_relationships(self, spec: Any, gen_schema: GenerationSchema) -> None:
        """Collect all foreignKey relationships from schema-level and field-level declarations."""
        schema_list = _attr(spec, "schema") or _attr(spec, "schema_") or []
        if not hasattr(schema_list, "__iter__"):
            return
        for schema_obj in schema_list:
            model_name = _attr(schema_obj, "name") or "unknown"
            # Schema-level relationships: from: model.field, to: model.field
            for rel in (_attr(schema_obj, "relationships") or []):
                self._add_relationship(rel, gen_schema, default_from_model=model_name)
            # Field-level relationships: to: model.field (from inferred from context)
            props = _attr(schema_obj, "properties") or []
            if not isinstance(props, dict):
                for fobj in props:
                    fname = _attr(fobj, "name") or "unknown"
                    for rel in (_attr(fobj, "relationships") or []):
                        self._add_relationship(
                            rel, gen_schema,
                            default_from_model=model_name,
                            default_from_field=fname,
                        )

    def _add_relationship(
        self,
        rel: Any,
        gen_schema: GenerationSchema,
        default_from_model: str = "",
        default_from_field: str = "",
    ) -> None:
        rel_type = (_attr(rel, "type") or "foreignKey")
        to_ref = str(_attr(rel, "to") or "")
        # "from" is a Python keyword; access via dict key works fine since _attr checks dicts first
        from_ref = str(_attr(rel, "from") or "")

        if not to_ref or "." not in to_ref:
            return
        to_model, to_field = to_ref.rsplit(".", 1)

        if from_ref and "." in from_ref:
            from_model, from_field = from_ref.rsplit(".", 1)
        else:
            from_model = default_from_model
            from_field = default_from_field

        if not from_model or not from_field:
            return

        key = (from_model, from_field, to_model, to_field)
        if not any(
            (r.from_model, r.from_field, r.to_model, r.to_field) == key
            for r in gen_schema.relationships
        ):
            gen_schema.relationships.append(RelationshipSpec(
                type=rel_type,
                from_model=from_model,
                from_field=from_field,
                to_model=to_model,
                to_field=to_field,
            ))

    def _parse_quality(self, quality: Any) -> list[QualityRule]:
        """Parse DataQuality entries (metric-level metadata, not value constraints)."""
        if not quality:
            return []
        items = quality if isinstance(quality, list) else [quality]
        rules: list[QualityRule] = []

        for item in items:
            d = _to_dict(item)
            rule_type = d.get("type", "library")
            metric = d.get("metric")

            # Find whichever operator is present
            for op in (
                "mustBe", "mustNotBe",
                "mustBeGreaterThan", "mustBeGreaterOrEqualTo",
                "mustBeLessThan", "mustBeLessOrEqualTo",
                "mustBeBetween", "mustNotBeBetween",
            ):
                if op in d:
                    rules.append(QualityRule(
                        type=rule_type,
                        metric=metric,
                        operator=op,
                        value=d[op],
                    ))
                    break
            else:
                if metric or rule_type:
                    rules.append(QualityRule(type=rule_type, metric=metric))

        return rules


# ------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------

def _attr(obj: Any, key: str, *, default: Any = None) -> Any:
    """Fetch *key* from *obj*, trying camelCase and snake_case.

    Plain dicts are checked by key lookup first (before getattr) to avoid
    shadowing by built-in dict methods such as ``items``, ``values``, ``keys``.
    """
    if obj is None:
        return default

    snake = re.sub(r"([A-Z])", r"_\1", key).lower().lstrip("_")

    if isinstance(obj, dict):
        for k in (key, snake):
            if k in obj and obj[k] is not None:
                return obj[k]
        return default

    for k in (key, snake):
        v = getattr(obj, k, _MISSING)
        if v is not _MISSING and v is not None:
            return v

    return default


def _to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):   # Pydantic v2
        return obj.model_dump()
    if hasattr(obj, "dict"):         # Pydantic v1
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return {}
