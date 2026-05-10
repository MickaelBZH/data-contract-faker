"""Unit tests for ContractParser — DataContract is mocked throughout."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from datacontract_faker.parser import ContractParser, ContractValidationError, _attr, _to_dict


# ---------------------------------------------------------------------------
# Mock builders
# ---------------------------------------------------------------------------

def _make_property(**kwargs):
    """Mimics an ODCS v3.1.0 SchemaProperty (array item with explicit ``name``)."""
    defaults = {
        # ODCS v3.1.0 canonical names
        "name": "col",
        "logicalType": None,
        "physicalType": None,
        "format": None,
        "required": False,
        "unique": False,
        "minimum": None,
        "maximum": None,
        "examples": None,
        "quality": None,
        # snake_case variants so _attr() doesn't pick up a truthy MagicMock
        "logical_type": None,
        "physical_type": None,
        "format_hint": None,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_schema_object(name: str, properties: list):
    """Mimics an ODCS v3.1.0 SchemaObject (array item)."""
    obj = MagicMock()
    obj.name = name
    obj.properties = properties
    obj.fields = None  # not the v3.1.0 name
    obj.quality = None
    return obj


def _make_spec(schema_objects: list):
    spec = MagicMock()
    spec.id = "test-id"
    spec.version = "1.0.0"
    spec.schema = schema_objects
    spec.schema_ = None
    spec.models = None
    return spec


def _patch_dc(spec, passed: bool = True):
    lint_result = MagicMock()
    lint_result.passed = passed
    lint_result.checks = []
    dc = MagicMock()
    dc.lint.return_value = lint_result
    dc.get_data_contract_specification.return_value = spec
    return patch("datacontract_faker.parser.DataContract", return_value=dc)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_raises_on_failed_lint():
    lint_result = MagicMock()
    lint_result.passed = False
    lint_result.checks = ["Missing required field: version"]
    dc = MagicMock()
    dc.lint.return_value = lint_result

    with patch("datacontract_faker.parser.DataContract", return_value=dc):
        with pytest.raises(ContractValidationError):
            ContractParser().parse_string("bad yaml")


def test_passes_on_valid_contract():
    prop = _make_property(name="id", logicalType="string", format="uuid", required=True)
    spec = _make_spec([_make_schema_object("orders", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert "orders" in schema.models


# ---------------------------------------------------------------------------
# Top-level schema parsing
# ---------------------------------------------------------------------------

def test_contract_id_extracted():
    spec = _make_spec([])
    spec.id = "my-contract-id"
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert schema.contract_id == "my-contract-id"


def test_version_from_top_level():
    spec = _make_spec([])
    spec.version = "2.5.0"
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert schema.contract_version == "2.5.0"


def test_multiple_schema_objects():
    a = _make_schema_object("orders", [])
    b = _make_schema_object("customers", [])
    spec = _make_spec([a, b])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert set(schema.models.keys()) == {"orders", "customers"}


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def test_logical_type_extracted():
    prop = _make_property(name="id", logicalType="string", format="uuid")
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    f = schema.models["tbl"].fields[0]
    assert f.logical_type == "string"
    assert f.format_hint == "uuid"


def test_physical_type_extracted():
    prop = _make_property(name="amt", logicalType="number", physicalType="decimal")
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert schema.models["tbl"].fields[0].physical_type == "decimal"


def test_required_false_by_default():
    prop = _make_property(name="notes", logicalType="string", required=False)
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert schema.models["tbl"].fields[0].required is False


def test_required_true_extracted():
    prop = _make_property(name="id", logicalType="string", format="uuid", required=True)
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert schema.models["tbl"].fields[0].required is True


def test_optional_field_gets_nullable_ratio():
    prop = _make_property(name="col", required=False)
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser(nullable_ratio=0.25).parse_string("")
    assert schema.models["tbl"].fields[0].nullable_ratio == 0.25


def test_required_field_has_zero_nullable_ratio():
    prop = _make_property(name="id", required=True)
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser(nullable_ratio=0.5).parse_string("")
    assert schema.models["tbl"].fields[0].nullable_ratio == 0.0


def test_unique_extracted():
    prop = _make_property(name="id", unique=True)
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert schema.models["tbl"].fields[0].unique is True


def test_minimum_maximum_extracted():
    prop = _make_property(name="amount", logicalType="number", minimum=0.01, maximum=9999.99)
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    f = schema.models["tbl"].fields[0]
    assert f.minimum == 0.01
    assert f.maximum == 9999.99


def test_examples_extracted():
    prop = _make_property(name="status", examples=["pending", "shipped"])
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert schema.models["tbl"].fields[0].examples == ["pending", "shipped"]


# ---------------------------------------------------------------------------
# Quality rule parsing  (ODCS v3.1.0: type + metric + operator)
# ---------------------------------------------------------------------------

def test_quality_rule_parsed():
    quality = [{"type": "library", "metric": "nullValues", "mustBe": 0}]
    prop = _make_property(name="col", quality=quality)
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    rules = schema.models["tbl"].fields[0].quality_rules
    assert len(rules) == 1
    assert rules[0].metric == "nullValues"
    assert rules[0].operator == "mustBe"
    assert rules[0].value == 0


def test_must_be_between_quality_rule_parsed():
    quality = [{"type": "library", "metric": "rowCount", "mustBeBetween": [100, 10000]}]
    prop = _make_property(name="col", quality=quality)
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    rules = schema.models["tbl"].fields[0].quality_rules
    assert rules[0].operator == "mustBeBetween"
    assert rules[0].value == [100, 10000]


def test_no_quality_gives_empty_list():
    prop = _make_property(name="col", quality=None)
    spec = _make_spec([_make_schema_object("tbl", [prop])])
    with _patch_dc(spec):
        schema = ContractParser().parse_string("")
    assert schema.models["tbl"].fields[0].quality_rules == []


# ---------------------------------------------------------------------------
# _attr / _to_dict helpers
# ---------------------------------------------------------------------------

def test_attr_camel_access():
    m = MagicMock()
    m.logicalType = "timestamp"
    assert _attr(m, "logicalType") == "timestamp"


def test_attr_dict_access():
    assert _attr({"minimum": 5.0}, "minimum") == 5.0


def test_attr_returns_default_on_miss():
    assert _attr({}, "missing", default="x") == "x"


def test_to_dict_plain():
    assert _to_dict({"a": 1}) == {"a": 1}


def test_to_dict_pydantic_v2():
    m = MagicMock()
    m.model_dump.return_value = {"key": "val"}
    assert _to_dict(m) == {"key": "val"}


def test_nullable_ratio_out_of_range():
    with pytest.raises(ValueError):
        ContractParser(nullable_ratio=2.0)
