"""Evaluate local CDSCO and ICMR evidence using versioned rules."""

from .evaluator import evaluate
from .models import Case, Evaluation

__all__ = ["Case", "Evaluation", "evaluate"]
