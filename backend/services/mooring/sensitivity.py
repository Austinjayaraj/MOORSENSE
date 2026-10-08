"""Deterministic one-at-a-time sensitivity analysis.

Varies one parameter at a time to determine which unknown engineering
parameters most affect the tension estimate. Only varies parameters
where explicit ranges are supplied.

This is a RESEARCH TOOL, not an engineering assessment.
"""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict


class SensitivitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameter: str
    baseline: float
    low: float
    high: float
    unit: str = ""
    provenance: str = "SCENARIO_ASSUMPTION"
    notes: str | None = None


class SensitivityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameter: str
    baseline: float
    low: float
    high: float
    unit: str
    baseline_response: float | None = None
    low_response: float | None = None
    high_response: float | None = None
    response_range: float | None = None
    relative_sensitivity: float | None = None
    provenance: str


def run_sensitivity(specs: list[SensitivitySpec],
                    compute_fn,
                    baseline_params: dict) -> list[SensitivityResult]:
    """Run one-at-a-time sensitivity analysis.

    Args:
        specs: List of parameters to vary with their ranges
        compute_fn: callable(params_dict) -> float | None
        baseline_params: Baseline parameter values

    Returns list of SensitivityResult, one per spec.
    """
    results = []
    baseline_response = _safe_call(compute_fn, baseline_params)

    for spec in specs:
        low_params = {**baseline_params, spec.parameter: spec.low}
        high_params = {**baseline_params, spec.parameter: spec.high}

        low_r = _safe_call(compute_fn, low_params)
        high_r = _safe_call(compute_fn, high_params)
        response_range = None
        rel_sensitivity = None
        if low_r is not None and high_r is not None:
            response_range = round(abs(high_r - low_r), 2)
            param_range = abs(spec.high - spec.low)
            if baseline_response and baseline_response != 0 and param_range != 0:
                rel_sensitivity = round(
                    (response_range / abs(spec.baseline)) /
                    (abs(baseline_response) / abs(spec.baseline)),
                    4) if spec.baseline != 0 else None

        results.append(SensitivityResult(
            parameter=spec.parameter,
            baseline=spec.baseline,
            low=spec.low,
            high=spec.high,
            unit=spec.unit,
            baseline_response=baseline_response,
            low_response=low_r,
            high_response=high_r,
            response_range=response_range,
            relative_sensitivity=rel_sensitivity,
            provenance=spec.provenance,
        ))

    return results


def _safe_call(fn, params):
    try:
        result = fn(params)
        return float(result) if result is not None else None
    except Exception:
        return None
