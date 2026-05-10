"""datacontract-faker: synthetic data generation from ODCS data contracts."""
from .exporter import Exporter
from .generator import SyntheticGenerator
from .models import FieldSpec, GenerationSchema, OutputFormat, QualityRule
from .parser import ContractParser, ContractValidationError

__all__ = [
    "ContractParser",
    "ContractValidationError",
    "SyntheticGenerator",
    "Exporter",
    "FieldSpec",
    "GenerationSchema",
    "OutputFormat",
    "QualityRule",
]

__version__ = "0.1.0"
