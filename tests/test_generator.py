"""Unit tests for SyntheticGenerator — uses internal models only, no external deps."""
import polars as pl
import pytest
from faker import Faker

from datacontract_faker.generator import GenerationError, SyntheticGenerator
from datacontract_faker.mapper import ProviderMapper
from datacontract_faker.models import FieldSpec, GenerationSchema, ModelSpec


def _make_schema(*fields: FieldSpec, model_name: str = "test") -> GenerationSchema:
    schema = GenerationSchema(contract_id="test-id", contract_version="1.0.0")
    schema.models[model_name] = ModelSpec(name=model_name, fields=list(fields))
    return schema


@pytest.fixture()
def mapper() -> ProviderMapper:
    return ProviderMapper()


# ---------------------------------------------------------------------------
# Basic generation
# ---------------------------------------------------------------------------

def test_generates_correct_row_count():
    schema = _make_schema(FieldSpec(name="val", logical_type="string"))
    df = SyntheticGenerator(schema, rows=50, seed=1).generate_model("test")
    assert len(df) == 50


def test_generates_all_columns():
    fields = [
        FieldSpec(name="id",     logical_type="string",  format_hint="uuid"),
        FieldSpec(name="email",  logical_type="string",  format_hint="email"),
        FieldSpec(name="amount", logical_type="number"),
    ]
    df = SyntheticGenerator(_make_schema(*fields), rows=10, seed=42).generate_model("test")
    assert list(df.columns) == ["id", "email", "amount"]


def test_generate_all_returns_all_models():
    s = GenerationSchema(contract_id="x", contract_version="1")
    s.models["a"] = ModelSpec("a", [FieldSpec(name="v", logical_type="integer")])
    s.models["b"] = ModelSpec("b", [FieldSpec(name="v", logical_type="integer")])
    result = SyntheticGenerator(s, rows=5, seed=0).generate_all()
    assert set(result.keys()) == {"a", "b"}
    assert all(len(df) == 5 for df in result.values())


# ---------------------------------------------------------------------------
# Nullable fields
# ---------------------------------------------------------------------------

def test_optional_field_all_null_at_ratio_1():
    field = FieldSpec(name="notes", logical_type="string", required=False, nullable_ratio=1.0)
    df = SyntheticGenerator(_make_schema(field), rows=20, seed=7).generate_model("test")
    assert df["notes"].is_null().all()


def test_required_field_no_nulls():
    field = FieldSpec(name="id", logical_type="string", format_hint="uuid", required=True)
    df = SyntheticGenerator(_make_schema(field), rows=50, seed=7).generate_model("test")
    assert df["id"].is_not_null().all()


# ---------------------------------------------------------------------------
# Examples pool
# ---------------------------------------------------------------------------

def test_examples_values_respected():
    field = FieldSpec(
        name="status",
        logical_type="string",
        examples=["pending", "shipped", "delivered"],
    )
    df = SyntheticGenerator(_make_schema(field), rows=100, seed=3).generate_model("test")
    assert set(df["status"].unique().to_list()).issubset({"pending", "shipped", "delivered"})


# ---------------------------------------------------------------------------
# minimum / maximum constraints  (ODCS v3.1.0 field-level bounds)
# ---------------------------------------------------------------------------

def test_number_minimum_maximum():
    field = FieldSpec(name="amount", logical_type="number", minimum=10.0, maximum=50.0)
    df = SyntheticGenerator(_make_schema(field), rows=200, seed=5).generate_model("test")
    assert df["amount"].is_between(10.0, 50.0).all()


def test_integer_minimum_maximum_returns_int():
    field = FieldSpec(name="score", logical_type="integer", minimum=1, maximum=10)
    df = SyntheticGenerator(_make_schema(field), rows=100, seed=5).generate_model("test")
    assert df["score"].is_between(1, 10).all()
    assert df["score"].dtype == pl.Int64


def test_physical_type_integer_bounds():
    field = FieldSpec(name="qty", physical_type="bigint", minimum=0, maximum=999)
    df = SyntheticGenerator(_make_schema(field), rows=50, seed=9).generate_model("test")
    assert df["qty"].is_between(0, 999).all()


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------

def test_unique_field_no_duplicates():
    field = FieldSpec(name="id", logical_type="string", format_hint="uuid", unique=True)
    df = SyntheticGenerator(_make_schema(field), rows=500, seed=99).generate_model("test")
    assert df["id"].n_unique() == 500


def test_unique_examples_pool_exhausted_raises():
    field = FieldSpec(
        name="code",
        logical_type="string",
        examples=["x", "y"],
        unique=True,
    )
    gen = SyntheticGenerator(_make_schema(field), rows=3, seed=0)
    with pytest.raises(GenerationError, match="exhausted"):
        gen.generate_model("test")


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

def test_seed_reproducible():
    field = FieldSpec(name="val", logical_type="string", format_hint="email")
    schema = _make_schema(field)
    df1 = SyntheticGenerator(schema, rows=20, seed=42).generate_model("test")
    df2 = SyntheticGenerator(schema, rows=20, seed=42).generate_model("test")
    assert df1["val"].to_list() == df2["val"].to_list()


# ---------------------------------------------------------------------------
# Format-hint-driven generation (ODCS string sub-types)
# ---------------------------------------------------------------------------

def test_uuid_format_hint_produces_uuid():
    field = FieldSpec(name="id", logical_type="string", format_hint="uuid")
    df = SyntheticGenerator(_make_schema(field), rows=10, seed=1).generate_model("test")
    for val in df["id"].to_list():
        assert len(val) == 36 and val.count("-") == 4


def test_email_format_hint_produces_email():
    field = FieldSpec(name="em", logical_type="string", format_hint="email")
    df = SyntheticGenerator(_make_schema(field), rows=10, seed=1).generate_model("test")
    assert all("@" in v for v in df["em"].to_list())
