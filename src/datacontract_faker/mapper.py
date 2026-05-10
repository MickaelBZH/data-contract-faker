"""ProviderMapper: resolves ODCS v3.1.0 type descriptors to Faker provider callables.

ODCS v3.1.0 type system
------------------------
``logicalType`` is a closed enum:
    string | date | timestamp | time | number | integer | object | array | boolean

String sub-types are expressed via ``format``:
    email | uuid | uri | hostname | ipv4 | ipv6 | password | byte | binary

``physicalType`` is a free-form vendor string (decimal, varchar, bigint, …).

Resolution priority
-------------------
1. logicalType + format   (e.g. string+email → fake.email())
2. logicalType alone      (e.g. timestamp → fake.date_time().isoformat())
3. physicalType           (e.g. decimal → fake.pydecimal())
4. Fallback               → fake.word()
"""
from __future__ import annotations

from typing import Any, Callable

from faker import Faker

ProviderFn = Callable[[Faker], Any]


# ---------------------------------------------------------------------------
# Tier 1 — logicalType + format  (highest fidelity)
# ODCS string formats: email | uuid | uri | hostname | ipv4 | ipv6 | password | byte | binary
# ---------------------------------------------------------------------------
LOGICAL_FORMAT_MAP: dict[str, ProviderFn] = {
    # String sub-types
    "string:email":    lambda f: f.email(),
    "string:uuid":     lambda f: f.uuid4(),
    "string:uri":      lambda f: f.uri(),
    "string:hostname": lambda f: f.hostname(),
    "string:ipv4":     lambda f: f.ipv4(),
    "string:ipv6":     lambda f: f.ipv6(),
    "string:password": lambda f: f.password(length=16),
    "string:byte":     lambda f: f.binary(length=16).hex(),
    "string:binary":   lambda f: f.binary(length=16),
    # Common extensions not in the ODCS format enum but seen in practice
    "string:phone":    lambda f: f.phone_number(),
    "string:url":      lambda f: f.url(),
    # Integer precision formats (ODCS v3.1.0)
    "integer:i32":     lambda f: f.random_int(min=-(2**31), max=2**31 - 1),
    "integer:i64":     lambda f: f.random_int(min=-(2**53), max=2**53),   # JS-safe range
    "integer:u64":     lambda f: f.random_int(min=0, max=2**53),          # unsigned
    # Number precision formats (ODCS v3.1.0)
    "number:f64":      lambda f: round(f.pyfloat(min_value=-1e9, max_value=1e9), 8),
}


# ---------------------------------------------------------------------------
# Tier 2 — logicalType alone  (ODCS canonical enum)
# ---------------------------------------------------------------------------
LOGICAL_TYPE_MAP: dict[str, ProviderFn] = {
    "string":    lambda f: f.word(),
    "date":      lambda f: f.date(),
    "timestamp": lambda f: f.date_time().isoformat(),
    "time":      lambda f: f.time(),
    "number":    lambda f: round(f.pyfloat(min_value=0, max_value=1_000_000), 4),
    "integer":   lambda f: f.random_int(min=0, max=100_000),
    "object":    lambda f: {},
    "array":     lambda f: [],
    "boolean":   lambda f: f.boolean(),
}


# ---------------------------------------------------------------------------
# Tier 3 — physicalType  (vendor / storage hint, free-form string)
# ---------------------------------------------------------------------------
PHYSICAL_TYPE_MAP: dict[str, ProviderFn] = {
    # String family
    "string":   lambda f: f.word(),
    "str":      lambda f: f.word(),
    "varchar":  lambda f: f.word(),
    "char":     lambda f: f.random_letter(),
    "text":     lambda f: f.text(max_nb_chars=200),
    "clob":     lambda f: f.text(max_nb_chars=500),
    # Integer family
    "int":      lambda f: f.random_int(min=0, max=100_000),
    "integer":  lambda f: f.random_int(min=0, max=100_000),
    "int8":     lambda f: f.random_int(min=0, max=127),
    "int16":    lambda f: f.random_int(min=0, max=32_767),
    "int32":    lambda f: f.random_int(min=0, max=2_147_483_647),
    "int64":    lambda f: f.random_int(min=0, max=9_007_199_254_740_991),
    "long":     lambda f: f.random_int(min=0, max=9_007_199_254_740_991),
    "bigint":   lambda f: f.random_int(min=0, max=9_007_199_254_740_991),
    "smallint": lambda f: f.random_int(min=0, max=32_767),
    "tinyint":  lambda f: f.random_int(min=0, max=255),
    # Float family
    "float":    lambda f: round(f.pyfloat(min_value=0, max_value=1_000_000), 4),
    "float32":  lambda f: round(f.pyfloat(min_value=0, max_value=1_000_000), 4),
    "float64":  lambda f: round(f.pyfloat(min_value=0, max_value=1_000_000), 8),
    "double":   lambda f: round(f.pyfloat(min_value=0, max_value=1_000_000), 8),
    "decimal":  lambda f: float(f.pydecimal(left_digits=10, right_digits=4, positive=True)),
    "numeric":  lambda f: float(f.pydecimal(left_digits=10, right_digits=4, positive=True)),
    "number":   lambda f: round(f.pyfloat(min_value=0, max_value=1_000_000), 4),
    # Boolean
    "boolean":  lambda f: f.boolean(),
    "bool":     lambda f: f.boolean(),
    # Temporal
    "date":      lambda f: f.date(),
    "timestamp": lambda f: f.date_time().isoformat(),
    "datetime":  lambda f: f.date_time().isoformat(),
    # Binary
    "binary":   lambda f: f.binary(length=16),
    "bytes":    lambda f: f.binary(length=16),
    "blob":     lambda f: f.binary(length=64),
    # Complex
    "array":    lambda f: [],
    "object":   lambda f: {},
    "map":      lambda f: {},
    "json":     lambda f: "{}",
    "variant":  lambda f: {},
}


class ProviderMapper:
    """Resolve ODCS type descriptors to a :class:`ProviderFn`.

    Args:
        logical_format_overrides: Extra / replacement ``logicalType:format`` entries.
        logical_overrides:        Extra / replacement ``logicalType`` entries.
        physical_overrides:       Extra / replacement ``physicalType`` entries.
    """

    def __init__(
        self,
        logical_format_overrides: dict[str, ProviderFn] | None = None,
        logical_overrides: dict[str, ProviderFn] | None = None,
        physical_overrides: dict[str, ProviderFn] | None = None,
    ) -> None:
        self._logical_format: dict[str, ProviderFn] = {
            **LOGICAL_FORMAT_MAP,
            **(logical_format_overrides or {}),
        }
        self._logical: dict[str, ProviderFn] = {
            **LOGICAL_TYPE_MAP,
            **(logical_overrides or {}),
        }
        self._physical: dict[str, ProviderFn] = {
            **PHYSICAL_TYPE_MAP,
            **(physical_overrides or {}),
        }

    def resolve(
        self,
        logical_type: str | None,
        physical_type: str | None,
        format_hint: str | None = None,
    ) -> ProviderFn:
        """Return the best :class:`ProviderFn` for the given type descriptors."""
        # Tier 1: logicalType + format
        if logical_type and format_hint:
            key = f"{_norm(logical_type)}:{_norm(format_hint)}"
            fn = self._logical_format.get(key)
            if fn:
                return fn

        # Tier 2: logicalType alone
        if logical_type:
            fn = self._logical.get(_norm(logical_type))
            if fn:
                return fn

        # Tier 3: physicalType
        if physical_type:
            # Strip length/precision suffixes like varchar(255) → varchar
            base = physical_type.split("(")[0].strip()
            fn = self._physical.get(_norm(base))
            if fn:
                return fn

        return lambda f: f.word()


def _norm(key: str) -> str:
    return key.lower().replace("-", "_").replace(" ", "_")
