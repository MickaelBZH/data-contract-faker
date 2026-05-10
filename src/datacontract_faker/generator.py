"""SyntheticGenerator: row-by-row synthetic data engine.

Generation priority per field
------------------------------
1. ``examples``  — pick from the contract's example values (closed set)
2. Bounded       — respect field-level ``minimum``/``maximum`` (ODCS v3.1.0)
3. Provider      — call the Faker provider resolved by :class:`ProviderMapper`

Uniqueness is enforced with a per-field ``seen`` set (not Faker's ``.unique`` proxy,
which has a hard collision ceiling).
"""
from __future__ import annotations

import logging
import random
import re
from datetime import date, datetime, timezone
from typing import Any

import polars as pl
import rstr
from faker import Faker

from .mapper import ProviderMapper, ProviderFn
from .models import FieldSpec, GenerationSchema

logger = logging.getLogger(__name__)

_MAX_UNIQUE_ATTEMPTS = 1_000


class GenerationError(Exception):
    """Raised when the generator cannot satisfy a field's constraints."""


class SyntheticGenerator:
    """Generate synthetic :class:`polars.DataFrame` objects from a :class:`GenerationSchema`.

    Args:
        schema:  Parsed generation schema.
        rows:    Number of rows per model.
        locale:  Faker locale string (default ``"en_US"``).
        seed:    Optional integer seed for reproducibility.
        mapper:  Custom :class:`ProviderMapper`; defaults to the standard one.
    """

    def __init__(
        self,
        schema: GenerationSchema,
        rows: int = 100,
        locale: str = "en_US",
        seed: int | None = None,
        mapper: ProviderMapper | None = None,
    ) -> None:
        self.schema = schema
        self.rows = rows
        self.fake = Faker(locale)
        self.mapper = mapper or ProviderMapper()

        if seed is not None:
            Faker.seed(seed)
            random.seed(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_all(self) -> dict[str, pl.DataFrame]:
        """Generate data for every model, respecting foreign-key relationships."""
        # Build FK lookup: (from_model, from_field) → (to_model, to_field)
        fk_map: dict[tuple[str, str], tuple[str, str]] = {}
        for rel in self.schema.relationships:
            if rel.type == "foreignKey":
                fk_map[(rel.from_model, rel.from_field)] = (rel.to_model, rel.to_field)

        order = self._topo_sort(fk_map)
        results: dict[str, pl.DataFrame] = {}
        # {model_name: {field_name: [generated values]}}
        column_pools: dict[str, dict[str, list[Any]]] = {}

        for model_name in order:
            field_fk_pools: dict[str, list[Any]] = {}
            for f in self.schema.models[model_name].fields:
                ref = fk_map.get((model_name, f.name))
                if ref is not None:
                    to_model, to_field = ref
                    pool = (column_pools.get(to_model) or {}).get(to_field)
                    if pool:
                        field_fk_pools[f.name] = pool

            df = self.generate_model(model_name, fk_pools=field_fk_pools)
            results[model_name] = df
            column_pools[model_name] = {col: df[col].to_list() for col in df.columns}

        return results

    def _topo_sort(self, fk_map: dict[tuple[str, str], tuple[str, str]]) -> list[str]:
        """Return model names ordered so each model is generated after its FK targets."""
        deps: dict[str, set[str]] = {name: set() for name in self.schema.models}
        for (from_model, _), (to_model, _) in fk_map.items():
            if from_model in deps and to_model in deps and from_model != to_model:
                deps[from_model].add(to_model)

        order: list[str] = []
        ready = [m for m, d in deps.items() if not d]
        remaining = {m: set(d) for m, d in deps.items() if d}

        while ready:
            node = ready.pop(0)
            order.append(node)
            for m in list(remaining):
                remaining[m].discard(node)
                if not remaining[m]:
                    ready.append(m)
                    del remaining[m]

        for m in self.schema.models:
            if m not in order:
                order.append(m)

        return order

    def generate_model(self, model_name: str, fk_pools: dict[str, list[Any]] | None = None) -> pl.DataFrame:
        """Generate *self.rows* rows for a single model.

        Args:
            fk_pools: Optional mapping of field name → pool of FK values to sample from.
        """
        model = self.schema.models[model_name]
        fk_pools = fk_pools or {}

        providers: dict[str, ProviderFn] = {
            f.name: self.mapper.resolve(f.logical_type, f.physical_type, f.format_hint)
            for f in model.fields
        }
        seen: dict[str, set[Any]] = {f.name: set() for f in model.fields if f.unique}
        data: dict[str, list[Any]] = {f.name: [] for f in model.fields}

        for _ in range(self.rows):
            for field in model.fields:
                value = self._generate_value(
                    field,
                    providers[field.name],
                    seen.get(field.name),
                    fk_pool=fk_pools.get(field.name),
                )
                data[field.name].append(value)

        return pl.DataFrame(data)

    # ------------------------------------------------------------------
    # Core generation logic
    # ------------------------------------------------------------------

    def _generate_value(
        self,
        field: FieldSpec,
        provider: ProviderFn,
        seen: set[Any] | None,
        fk_pool: list[Any] | None = None,
    ) -> Any:
        # Nullable: optional fields emit None at the configured ratio.
        if not field.required and random.random() < field.nullable_ratio:
            return None

        # FK pool: sample from referenced model's values to enforce referential integrity.
        if fk_pool is not None:
            if seen is not None:
                remaining = [v for v in fk_pool if v not in seen]
                if remaining:
                    val = random.choice(remaining)
                    seen.add(val)
                    return val
            return random.choice(fk_pool)

        # Structural types — recurse before touching the flat provider.
        if (field.logical_type or "").lower() == "object" and field.nested_fields:
            return self._generate_object(field.nested_fields)

        if (field.logical_type or "").lower() == "array":
            return self._generate_array(field)

        # Examples pool takes priority — carries real semantic meaning.
        if field.examples:
            return self._pick_from_pool(field.examples, field.name, seen)

        # Pattern constraint — generate a conforming string via rstr.
        if field.pattern:
            return rstr.xeger(field.pattern)

        # String length constraint — only when no format_hint provides a richer generator.
        if (field.min_length is not None or field.max_length is not None) and not field.format_hint:
            lo = field.min_length or 1
            hi = field.max_length or max(lo, 64)
            return self.fake.pystr(min_chars=lo, max_chars=hi)

        is_bounded = (
            field.minimum is not None
            or field.maximum is not None
            or field.exclusive_minimum is not None
            or field.exclusive_maximum is not None
            or field.multiple_of is not None
        )

        if seen is not None:
            if is_bounded:
                value = self._unique_bounded(field, provider, seen)
            else:
                value = self._unique_free(field, provider, seen)
        elif is_bounded:
            value = self._apply_bounds(field, provider)
        else:
            value = provider(self.fake)

        # Enforce maxLength on string outputs even when a format hint produced the value.
        if isinstance(value, str) and field.max_length is not None and len(value) > field.max_length:
            value = value[: field.max_length]
        return value

    def _generate_object(self, nested_fields: list[FieldSpec]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for f in nested_fields:
            provider = self.mapper.resolve(f.logical_type, f.physical_type, f.format_hint)
            result[f.name] = self._generate_value(f, provider, None)
        return result

    def _generate_array(self, field: FieldSpec) -> list[Any]:
        if field.items_spec is None:
            return []
        # Cap at 5 items to keep output readable; still honours minItems.
        n = random.randint(field.min_items, min(field.max_items, 5))
        item = field.items_spec
        provider = self.mapper.resolve(item.logical_type, item.physical_type, item.format_hint)
        if not field.unique_items:
            return [self._generate_value(item, provider, None) for _ in range(n)]
        seen: set[Any] = set()
        result: list[Any] = []
        attempts = 0
        while len(result) < n and attempts < n * 10:
            val = self._generate_value(item, provider, None)
            attempts += 1
            hashable = val if not isinstance(val, dict) else str(val)
            if hashable not in seen:
                seen.add(hashable)
                result.append(val)
        return result

    # ------------------------------------------------------------------
    # Bounds application  (ODCS v3.1.0: minimum/maximum on the field)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(value: Any, *, is_timestamp: bool) -> "date | datetime":
        """Parse an ODCS date/timestamp bound string into a naive date or datetime."""
        s = str(value).strip().rstrip("Z")
        if is_timestamp:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            raise ValueError(f"Cannot parse timestamp bound: {value!r}")
        return date.fromisoformat(s[:10])

    def _apply_bounds(self, field: FieldSpec, provider: ProviderFn) -> Any:
        lo, hi = field.minimum, field.maximum
        excl_lo, excl_hi = field.exclusive_minimum, field.exclusive_maximum
        mult = field.multiple_of
        effective = (field.effective_type or "").lower()

        if effective == "date":
            start = self._parse_date(lo, is_timestamp=False) if lo is not None else "-100y"
            end = self._parse_date(hi, is_timestamp=False) if hi is not None else "today"
            return self.fake.date_between(start_date=start, end_date=end)

        if effective in ("timestamp", "time"):
            start = self._parse_date(lo, is_timestamp=True) if lo is not None else "-30y"
            end = self._parse_date(hi, is_timestamp=True) if hi is not None else "now"
            return self.fake.date_time_between(start_date=start, end_date=end).isoformat()

        try:
            lo_f = float(lo) if lo is not None else None
            hi_f = float(hi) if hi is not None else None
            excl_lo_f = float(excl_lo) if excl_lo is not None else None
            excl_hi_f = float(excl_hi) if excl_hi is not None else None
            mult_f = float(mult) if mult is not None else None
        except (TypeError, ValueError):
            logger.warning(
                "Field '%s': cannot coerce numeric bounds to float; "
                "falling back to unconstrained provider.",
                field.name,
            )
            return provider(self.fake)

        is_int = effective == "integer" or any(
            t in (field.physical_type or "").lower()
            for t in ("int", "long", "bigint", "smallint", "tinyint")
        )
        epsilon = 1 if is_int else 0.0001

        # Fold exclusive bounds into the inclusive range.
        eff_lo = lo_f
        if excl_lo_f is not None:
            candidate = excl_lo_f + epsilon
            eff_lo = candidate if eff_lo is None else max(eff_lo, candidate)
        eff_hi = hi_f
        if excl_hi_f is not None:
            candidate = excl_hi_f - epsilon
            eff_hi = candidate if eff_hi is None else min(eff_hi, candidate)

        # Default the missing side. Use decimal(p,s) precision when available.
        pt_max = self._max_from_physical(field.physical_type)
        default_hi = pt_max if pt_max is not None else (2**31 - 1 if is_int else 1e9)
        default_lo = -default_hi if not is_int else -(2**31)
        if eff_lo is None:
            eff_lo = default_lo
        if eff_hi is None:
            eff_hi = default_hi

        if eff_lo > eff_hi:
            logger.warning("Field '%s': bounds collapse to empty range; using lower bound.", field.name)
            return int(eff_lo) if is_int else round(eff_lo, 4)

        if is_int:
            val: float = random.randint(int(eff_lo), int(eff_hi))
        else:
            val = round(random.uniform(eff_lo, eff_hi), 4)

        # Snap to multipleOf, keeping the value inside [eff_lo, eff_hi].
        if mult_f is not None and mult_f > 0:
            if is_int:
                step = max(int(mult_f), 1)
                val = (int(val) // step) * step
                if val < eff_lo:
                    val += step
                if val > eff_hi:
                    val -= step
            else:
                val = round(round(val / mult_f) * mult_f, 4)
                if val < eff_lo:
                    val = round(val + mult_f, 4)
                elif val > eff_hi:
                    val = round(val - mult_f, 4)

        return val

    @staticmethod
    def _max_from_physical(physical_type: str | None) -> float | None:
        """Derive the maximum representable magnitude from decimal(p,s) / numeric(p,s)."""
        if not physical_type:
            return None
        m = re.match(
            r"\s*(?:decimal|numeric)\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)",
            physical_type,
            re.IGNORECASE,
        )
        if not m:
            return None
        precision, scale = int(m.group(1)), int(m.group(2))
        if precision < scale:
            return None
        return float(10 ** (precision - scale)) - float(10 ** -scale)

    # ------------------------------------------------------------------
    # Uniqueness helpers
    # ------------------------------------------------------------------

    def _unique_free(self, field: FieldSpec, provider: ProviderFn, seen: set) -> Any:
        for _ in range(_MAX_UNIQUE_ATTEMPTS):
            val = provider(self.fake)
            if val not in seen:
                seen.add(val)
                return val
        raise GenerationError(
            f"Could not produce a unique value for field '{field.name}' "
            f"after {_MAX_UNIQUE_ATTEMPTS} attempts. "
            "Consider increasing provider cardinality or reducing row count."
        )

    def _unique_bounded(self, field: FieldSpec, provider: ProviderFn, seen: set) -> Any:
        for _ in range(_MAX_UNIQUE_ATTEMPTS):
            val = self._apply_bounds(field, provider)
            if val not in seen:
                seen.add(val)
                return val
        raise GenerationError(
            f"Could not produce a unique bounded value for field '{field.name}' "
            f"after {_MAX_UNIQUE_ATTEMPTS} attempts. "
            "The minimum/maximum range may be too narrow for the requested row count."
        )

    def _pick_from_pool(self, pool: list[Any], field_name: str, seen: set | None) -> Any:
        if seen is None:
            return random.choice(pool)
        remaining = [v for v in pool if v not in seen]
        if not remaining:
            raise GenerationError(
                f"Field '{field_name}' is marked unique but its examples pool "
                f"({len(pool)} values) is exhausted. Add more values or reduce row count."
            )
        val = random.choice(remaining)
        seen.add(val)
        return val
