# datacontract-faker

[![CI](https://img.shields.io/github/actions/workflow/status/MickaelBZH/data-contract-faker/ci.yml?branch=main&label=CI&logo=github)](https://github.com/MickaelBZH/data-contract-faker/actions)
[![PyPI](https://img.shields.io/pypi/v/datacontract-faker?logo=pypi&logoColor=white)](https://pypi.org/project/datacontract-faker/)
[![Python](https://img.shields.io/pypi/pyversions/datacontract-faker?logo=python&logoColor=white)](https://pypi.org/project/datacontract-faker/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

`datacontract-faker` reads an [ODCS v3.1.0](https://github.com/bitol-io/open-data-contract-standard) data contract and produces realistic, contract-compliant synthetic data — as a CLI tool or a Python library.

```bash
datacontract-faker generate orders.yaml -r 50000 -o data/orders.parquet -f parquet
```

---

## Highlights

- **Strict contract compliance** — `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf`, `minLength`, `maxLength`, `pattern`, `examples`, `format`, and length-constrained types are all enforced on every row.
- **Foreign-key integrity** — declares from `relationships:` are honored across models. Referenced tables are generated first; child rows sample real parent keys.
- **Nested + array types** — recursive `object` fields and `array` items (including arrays of objects) generate properly typed values.
- **Reproducible** — pin `--seed` for byte-identical output across runs.
- **Four output formats** — JSON, JSONL, CSV, Parquet (via `polars` + `pyarrow`).
- **Locale-aware** — any [Faker locale](https://faker.readthedocs.io/en/master/locales.html) (`en_US`, `de_DE`, `ja_JP`, …).
- **Library-first** — every component (`ContractParser`, `SyntheticGenerator`, `ProviderMapper`, `Exporter`) is independently importable.

---

## Install

```bash
pip install datacontract-faker          # standard
pipx install datacontract-faker         # isolated CLI
poetry add datacontract-faker           # poetry projects
```

Requires Python ≥ 3.11.

---

## CLI

### `generate`

Generate synthetic data from a contract.

```bash
datacontract-faker generate CONTRACT [OPTIONS]
```

| Option | Short | Default | Description |
|---|---|---|---|
| `CONTRACT` | — | **required** | Path to the ODCS contract (YAML), as a positional argument |
| `--rows INT` | `-r` | `100` | Rows to generate per model |
| `--output PATH` | `-o` | — | Output file. Omit to preview in the terminal |
| `--format` | `-f` | `json` | `csv` \| `json` \| `jsonl` \| `parquet` |
| `--model TEXT` | `-m` | all | Generate only this model |
| `--locale TEXT` | — | `en_US` | Faker locale |
| `--seed INT` | — | — | Seed for reproducible output |
| `--nullable-ratio FLOAT` | — | `0.1` | Probability of `null` for optional fields (0.0–1.0) |
| `--validate-only` | — | `false` | Only validate the contract; skip generation |
| `--verbose` | `-v` | `false` | Debug logging to stderr |

When a contract has multiple models and `--output` is set, each model is written to `{stem}_{model}{suffix}` — e.g. `data.parquet` becomes `data_orders.parquet`, `data_customers.parquet`.

### `inspect`

Render the parsed schema as a table — type, format, flags (`PK`, `req`, `uniq`, `→fk_target`), examples, and constraints.

```bash
datacontract-faker inspect CONTRACT [--nullable-ratio FLOAT]
```

### Recipes

```bash
# Preview 10 rows in the terminal
datacontract-faker generate contract.yaml -r 10

# Validate without generating
datacontract-faker generate contract.yaml --validate-only

# 1M rows to Parquet, deterministic
datacontract-faker generate contract.yaml -r 1000000 -o out.parquet -f parquet --seed 42

# Single model, German locale, NDJSON
datacontract-faker generate contract.yaml -m customers --locale de_DE -o cust.jsonl -f jsonl

# Stress-test null handling
datacontract-faker generate contract.yaml --nullable-ratio 0.5
```

---

## Python API

Every CLI capability is available as a library. Public exports from the top-level package:

```python
from datacontract_faker import (
    ContractParser, ContractValidationError,
    SyntheticGenerator,
    Exporter, OutputFormat,
    FieldSpec, GenerationSchema, QualityRule,
)
```

### End-to-end

```python
from pathlib import Path
from datacontract_faker import ContractParser, SyntheticGenerator, Exporter, OutputFormat

schema = ContractParser(nullable_ratio=0.05).load_and_validate(Path("contract.yaml"))

gen = SyntheticGenerator(schema, rows=10_000, seed=42, locale="en_US")
dataframes = gen.generate_all()   # dict[str, polars.DataFrame], FK-aware order

exporter = Exporter()
for name, df in dataframes.items():
    exporter.export(df, Path(f"output/{name}.parquet"), OutputFormat.PARQUET)
```

`generate_all()` honors foreign-key relationships: referenced models are generated first and child models sample real parent keys.

### Generate a single model

```python
df = gen.generate_model("orders")          # polars.DataFrame
df = gen.generate_model("orders", fk_pools={"customer_id": ["c1", "c2", "c3"]})
```

### Parse without file I/O

```python
schema = ContractParser().parse_string(contract_yaml_str)
```

### Custom Faker providers

Override or extend the type-to-provider resolution:

```python
from datacontract_faker.mapper import ProviderMapper
from datacontract_faker import SyntheticGenerator

mapper = ProviderMapper(
    logical_format_overrides={
        "string:product_sku": lambda f: f.bothify("???-####").upper(),
    },
    logical_overrides={
        "integer": lambda f: f.random_int(min=1000, max=9999),
    },
    physical_overrides={
        "decimal": lambda f: round(f.pyfloat(min_value=1, max_value=500), 2),
    },
)

gen = SyntheticGenerator(schema, rows=500, mapper=mapper)
```

---

## Output formats

| Format | Flag | Extension | Notes |
|---|---|---|---|
| JSON (array) | `json` | `.json` | Pretty-printed, UTF-8 |
| NDJSON | `jsonl` | `.jsonl` | One record per line, stream-friendly |
| CSV | `csv` | `.csv` | UTF-8, no index |
| Apache Parquet | `parquet` | `.parquet` | Columnar, compressed (recommended for large datasets) |

---

## Stack

[`datacontract-cli`](https://github.com/datacontract/datacontract-cli) for contract validation · [`Faker`](https://github.com/joke2k/faker) for synthetic values · [`polars`](https://github.com/pola-rs/polars) + [`pyarrow`](https://arrow.apache.org/docs/python/) for DataFrames and Parquet · [`rstr`](https://pypi.org/project/rstr/) for regex-conforming strings · [`Typer`](https://typer.tiangolo.com/) + [`Rich`](https://rich.readthedocs.io/) for the CLI.

---

## License

[MIT](LICENSE)
