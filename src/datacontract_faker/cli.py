"""CLI entry point for datacontract-faker."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .exporter import Exporter
from .generator import GenerationError, SyntheticGenerator
from .mapper import ProviderMapper
from .models import OutputFormat
from .parser import ContractParser, ContractValidationError

app = typer.Typer(
    name="datacontract-faker",
    help="[bold cyan]datacontract-faker[/bold cyan] — synthetic data from ODCS contracts.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
_out = Console()
_err = Console(stderr=True, style="bold red")


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------

@app.command()
def generate(
    contract: Path = typer.Argument(
        ...,
        help="Path to the ODCS data contract (YAML).",
        exists=True,
        readable=True,
    ),
    rows: int = typer.Option(
        100,
        "--rows", "-r",
        help="Number of rows to generate per model.",
        min=1,
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output file path.  Omit to preview in the terminal.",
        show_default=False,
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.JSON,
        "--format", "-f",
        help="Output format: csv | json | jsonl | parquet.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model", "-m",
        help="Generate only this model (default: all models).",
        show_default=False,
    ),
    locale: str = typer.Option("en_US", "--locale", help="Faker locale."),
    seed: Optional[int] = typer.Option(
        None, "--seed", help="Integer seed for reproducible output.", show_default=False
    ),
    nullable_ratio: float = typer.Option(
        0.1,
        "--nullable-ratio",
        help="Probability of None for optional fields (0.0–1.0).",
        min=0.0,
        max=1.0,
    ),
    validate_only: bool = typer.Option(
        False,
        "--validate-only",
        help="Only validate the contract; skip data generation.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Generate synthetic data from an ODCS data contract."""
    _configure_logging(verbose)

    # ── Parse & validate ─────────────────────────────────────────────────
    parser = ContractParser(nullable_ratio=nullable_ratio)
    try:
        _out.print(f"[cyan]Parsing contract:[/cyan] {contract}")
        schema = parser.load_and_validate(contract)
        _out.print(
            f"[green]✓[/green] Contract valid — "
            f"[bold]{len(schema.models)}[/bold] model(s): "
            + ", ".join(f"[italic]{n}[/italic]" for n in schema.models)
        )
    except ContractValidationError as exc:
        _err.print(f"Contract validation failed:\n{exc}")
        raise typer.Exit(1)

    if validate_only:
        raise typer.Exit(0)

    # ── Filter to requested model ─────────────────────────────────────────
    if model:
        if model not in schema.models:
            _err.print(
                f"Model [bold]{model!r}[/bold] not found. "
                f"Available: {list(schema.models.keys())}"
            )
            raise typer.Exit(1)
        schema.models = {model: schema.models[model]}

    # ── Generate ──────────────────────────────────────────────────────────
    generator = SyntheticGenerator(
        schema=schema,
        rows=rows,
        locale=locale,
        seed=seed,
        mapper=ProviderMapper(),
    )

    try:
        _out.print(f"[cyan]Generating[/cyan] {rows:,} row(s) …")
        dataframes = generator.generate_all()
    except GenerationError as exc:
        _err.print(str(exc))
        raise typer.Exit(1)

    # ── Export / preview ─────────────────────────────────────────────────
    exporter = Exporter()
    for model_name, df in dataframes.items():
        if output:
            # When multiple models are written, suffix the stem with the model name.
            out_path = (
                output.parent / f"{output.stem}_{model_name}{output.suffix}"
                if len(dataframes) > 1
                else output
            )
            exporter.export(df, out_path, fmt)
            _out.print(f"[green]✓[/green] [bold]{model_name}[/bold] → {out_path}")
        else:
            _out.print(f"\n[bold magenta]{model_name}[/bold magenta]")
            _print_preview(df)


# ---------------------------------------------------------------------------
# inspect command
# ---------------------------------------------------------------------------

@app.command()
def inspect(
    contract: Path = typer.Argument(
        ...,
        help="Path to the ODCS data contract (YAML).",
        exists=True,
        readable=True,
    ),
    nullable_ratio: float = typer.Option(
        0.1, "--nullable-ratio", min=0.0, max=1.0
    ),
) -> None:
    """Display the generation schema derived from a contract."""
    parser = ContractParser(nullable_ratio=nullable_ratio)
    try:
        schema = parser.load_and_validate(contract)
    except ContractValidationError as exc:
        _err.print(str(exc))
        raise typer.Exit(1)

    _out.print(
        f"[bold]Contract:[/bold] {schema.contract_id}  "
        f"[dim]v{schema.contract_version}[/dim]\n"
    )

    fk_lookup = {
        (r.from_model, r.from_field): f"{r.to_model}.{r.to_field}"
        for r in schema.relationships if r.type == "foreignKey"
    }

    for model_name, model_spec in schema.models.items():
        table = Table(
            title=f"Model: {model_name}",
            show_header=True,
            header_style="bold cyan",
            show_lines=True,
        )
        table.add_column("Field", style="bold")
        table.add_column("Logical Type")
        table.add_column("Physical Type")
        table.add_column("Format")
        table.add_column("Flags", justify="center")
        table.add_column("Examples", overflow="fold")
        table.add_column("Constraints", overflow="fold")

        for f in model_spec.fields:
            flags = []
            if f.primary_key:
                flags.append("[yellow]PK[/yellow]")
            if f.required:
                flags.append("[green]req[/green]")
            if f.unique and not f.primary_key:
                flags.append("[cyan]uniq[/cyan]")
            fk_target = fk_lookup.get((model_name, f.name))
            if fk_target:
                flags.append(f"[magenta]→{fk_target}[/magenta]")

            examples_str = (
                ", ".join(str(v) for v in (f.examples or [])[:5]) or "—"
            )

            constraints: list[str] = []
            if f.minimum is not None or f.maximum is not None:
                lo = f.minimum if f.minimum is not None else "−∞"
                hi = f.maximum if f.maximum is not None else "+∞"
                constraints.append(f"[{lo}, {hi}]")
            if f.exclusive_minimum is not None:
                constraints.append(f">{f.exclusive_minimum}")
            if f.exclusive_maximum is not None:
                constraints.append(f"<{f.exclusive_maximum}")
            if f.multiple_of is not None:
                constraints.append(f"×{f.multiple_of}")
            if f.min_length is not None or f.max_length is not None:
                lo = f.min_length if f.min_length is not None else 0
                hi = f.max_length if f.max_length is not None else "∞"
                constraints.append(f"len={lo}..{hi}")
            if f.pattern:
                constraints.append(f"pattern={f.pattern}")
            if (f.logical_type or "").lower() == "array":
                constraints.append(f"items={f.min_items}..{f.max_items}")
                if f.unique_items:
                    constraints.append("uniqueItems")

            table.add_row(
                f.name,
                f.logical_type or "—",
                f.physical_type or "—",
                f.format_hint or "—",
                " ".join(flags) or "—",
                examples_str,
                "; ".join(constraints) or "—",
            )
        _out.print(table)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_preview(df: "pl.DataFrame", max_rows: int = 5) -> None:  # noqa: F821
    table = Table(show_header=True, header_style="bold magenta", show_lines=False)
    for col in df.columns:
        table.add_column(col, overflow="fold")
    for row in df.head(max_rows).rows():
        table.add_row(*[str(v) if v is not None else "[dim]null[/dim]" for v in row])
    _out.print(table)
    if len(df) > max_rows:
        _out.print(f"  [dim]… {len(df) - max_rows:,} more rows[/dim]")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)


def main() -> None:
    app()
