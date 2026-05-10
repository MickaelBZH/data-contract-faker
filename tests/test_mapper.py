"""Unit tests for ProviderMapper — no external dependencies required."""
import pytest
from faker import Faker

from datacontract_faker.mapper import ProviderMapper, _norm


@pytest.fixture()
def fake() -> Faker:
    Faker.seed(0)
    return Faker("en_US")


@pytest.fixture()
def mapper() -> ProviderMapper:
    return ProviderMapper()


# ---------------------------------------------------------------------------
# _norm helper
# ---------------------------------------------------------------------------

def test_norm_lowercases():
    assert _norm("STRING") == "string"

def test_norm_replaces_hyphens():
    assert _norm("country-code") == "country_code"

def test_norm_replaces_spaces():
    assert _norm("first name") == "first_name"


# ---------------------------------------------------------------------------
# Tier 1: logicalType + format  (ODCS string sub-types)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ["email", "uuid", "uri", "ipv4", "ipv6", "hostname", "password"])
def test_string_formats_produce_value(mapper, fake, fmt):
    fn = mapper.resolve(logical_type="string", physical_type=None, format_hint=fmt)
    val = fn(fake)
    assert val is not None and isinstance(val, str)

def test_string_uuid_is_36_chars(mapper, fake):
    fn = mapper.resolve("string", None, "uuid")
    assert len(fn(fake)) == 36

def test_format_wins_over_bare_logical(mapper, fake):
    bare = mapper.resolve("string", None, None)(fake)
    with_fmt = mapper.resolve("string", None, "email")(fake)
    # Both are strings, but the email one must contain '@'
    assert "@" in with_fmt

def test_string_format_wins_over_physical(mapper, fake):
    fn = mapper.resolve(logical_type="string", physical_type="varchar", format_hint="uuid")
    val = fn(fake)
    assert len(val) == 36  # UUID, not a varchar word


# ---------------------------------------------------------------------------
# Tier 2: ODCS canonical logicalType alone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("logical", [
    "string", "date", "timestamp", "time",
    "number", "integer", "object", "array", "boolean",
])
def test_canonical_logical_types_resolve(mapper, fake, logical):
    fn = mapper.resolve(logical_type=logical, physical_type=None, format_hint=None)
    val = fn(fake)
    assert val is not None or val == {} or val == [] or isinstance(val, bool)

def test_integer_logical_returns_int(mapper, fake):
    fn = mapper.resolve("integer", None, None)
    assert isinstance(fn(fake), int)

def test_boolean_logical_returns_bool(mapper, fake):
    fn = mapper.resolve("boolean", None, None)
    assert isinstance(fn(fake), bool)

def test_number_logical_returns_float(mapper, fake):
    fn = mapper.resolve("number", None, None)
    assert isinstance(fn(fake), float)


# ---------------------------------------------------------------------------
# Tier 3: physicalType fallback
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("physical", [
    "decimal", "varchar", "bigint", "float64", "boolean",
    "timestamp", "date", "blob", "tinyint",
])
def test_physical_types_resolve(mapper, fake, physical):
    fn = mapper.resolve(logical_type=None, physical_type=physical, format_hint=None)
    assert fn(fake) is not None

def test_physical_strips_length_suffix(mapper, fake):
    fn = mapper.resolve(None, "varchar(255)", None)
    assert fn(fake) is not None

def test_integer_physical_returns_int(mapper, fake):
    fn = mapper.resolve(None, "int", None)
    assert isinstance(fn(fake), int)


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def test_unknown_all_returns_word(mapper, fake):
    fn = mapper.resolve("does_not_exist", "also_nope", "nope")
    assert isinstance(fn(fake), str)


# ---------------------------------------------------------------------------
# Custom overrides
# ---------------------------------------------------------------------------

def test_logical_format_override(fake):
    mapper = ProviderMapper(
        logical_format_overrides={"string:email": lambda f: "fixed@test.com"}
    )
    fn = mapper.resolve("string", None, "email")
    assert fn(fake) == "fixed@test.com"

def test_logical_override(fake):
    mapper = ProviderMapper(logical_overrides={"number": lambda f: 42.0})
    fn = mapper.resolve("number", None, None)
    assert fn(fake) == 42.0

def test_physical_override(fake):
    mapper = ProviderMapper(physical_overrides={"decimal": lambda f: 9.99})
    fn = mapper.resolve(None, "decimal", None)
    assert fn(fake) == 9.99
