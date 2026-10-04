"""Deterministic numerical primitives: ODE integration, sampling, alignment, deltas."""

from __future__ import annotations

from drw.numerics import metrics
from drw.numerics.alignment import AlignmentError, AlignmentResult, align
from drw.numerics.delta import Comparison, compare_outputs, compare_run
from drw.numerics.ode import SOLVER_METHODS, OdeModel, RhsFunction
from drw.numerics.sampling import SamplingDesign, expand_design

__all__ = [
    "SOLVER_METHODS",
    "AlignmentError",
    "AlignmentResult",
    "Comparison",
    "OdeModel",
    "RhsFunction",
    "SamplingDesign",
    "align",
    "compare_outputs",
    "compare_run",
    "expand_design",
    "metrics",
]
