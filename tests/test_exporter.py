"""Unit tests for Exporter."""
import json
from pathlib import Path

import polars as pl
import pytest

from datacontract_faker.exporter import Exporter
from datacontract_faker.models import OutputFormat


@pytest.fixture()
def df() -> pl.DataFrame:
    return pl.DataFrame({
        "id": ["a", "b", "c"],
        "value": [1.1, 2.2, 3.3],
        "flag": [True, False, True],
    })


@pytest.fixture()
def exporter() -> Exporter:
    return Exporter()


def test_csv_export(tmp_path, df, exporter):
    out = tmp_path / "out.csv"
    exporter.export(df, out, OutputFormat.CSV)
    loaded = pl.read_csv(out)
    assert list(loaded.columns) == list(df.columns)
    assert len(loaded) == 3


def test_json_export(tmp_path, df, exporter):
    out = tmp_path / "out.json"
    exporter.export(df, out, OutputFormat.JSON)
    records = json.loads(out.read_text())
    assert len(records) == 3
    assert records[0]["id"] == "a"


def test_jsonl_export(tmp_path, df, exporter):
    out = tmp_path / "out.jsonl"
    exporter.export(df, out, OutputFormat.JSONL)
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(lines) == 3
    assert lines[1]["value"] == pytest.approx(2.2)


def test_parquet_export(tmp_path, df, exporter):
    out = tmp_path / "out.parquet"
    exporter.export(df, out, OutputFormat.PARQUET)
    loaded = pl.read_parquet(out)
    assert list(loaded.columns) == list(df.columns)
    assert len(loaded) == 3


def test_creates_parent_dirs(tmp_path, df, exporter):
    out = tmp_path / "nested" / "dir" / "out.csv"
    exporter.export(df, out, OutputFormat.CSV)
    assert out.exists()


def test_unsupported_format_raises(tmp_path, df, exporter):
    with pytest.raises(ValueError, match="Unsupported"):
        exporter.export(df, tmp_path / "x", "xml")  # type: ignore[arg-type]
