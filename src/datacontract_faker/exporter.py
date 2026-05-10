"""Exporter: writes a polars DataFrame to disk in the requested format."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import polars as pl

from .models import OutputFormat

logger = logging.getLogger(__name__)


class Exporter:
    """Write a :class:`polars.DataFrame` to a file.

    Supported formats: CSV, JSON (records), JSONL (newline-delimited), Parquet.
    """

    def export(self, df: pl.DataFrame, output_path: Path, fmt: OutputFormat) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        dispatch = {
            OutputFormat.CSV: self._to_csv,
            OutputFormat.JSON: self._to_json,
            OutputFormat.JSONL: self._to_jsonl,
            OutputFormat.PARQUET: self._to_parquet,
        }
        writer = dispatch.get(fmt)
        if writer is None:
            raise ValueError(f"Unsupported output format: {fmt!r}")

        writer(df, output_path)
        logger.info("Exported %d rows → %s (%s)", len(df), output_path, fmt.value)

    # ------------------------------------------------------------------
    # Format writers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_csv(df: pl.DataFrame, path: Path) -> None:
        df.write_csv(path)

    @staticmethod
    def _to_json(df: pl.DataFrame, path: Path) -> None:
        # polars write_json lacks indent support; serialize via to_dicts() for pretty output.
        path.write_text(
            json.dumps(df.to_dicts(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _to_jsonl(df: pl.DataFrame, path: Path) -> None:
        df.write_ndjson(path)

    @staticmethod
    def _to_parquet(df: pl.DataFrame, path: Path) -> None:
        df.write_parquet(path)
