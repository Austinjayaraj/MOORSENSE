"""Uncertainty framework for mooring Digital Twin.

POLICY: Never manufacture uncertainty bounds.
A parameter may only enter uncertainty propagation when an explicit,
defensible distribution exists from an authoritative or published source.

Current state for all OMNI stations: NOT_QUANTIFIED.
No defensible uncertainty bounds exist for MBL, pretension, line geometry,
or water depth at the required precision.

When bounds ARE provided (e.g. a SCENARIO_ASSUMPTION for research sensitivity),
they must be explicitly labeled to avoid confusion with measured uncertainty.
"""
from __future__ import annotations
import math
import random
from pydantic import BaseModel, ConfigDict
from typing import Literal

DistributionType = Literal["UNIFORM", "NORMAL", "LOGNORMAL", "TRIANGULAR"]
UncertaintySource = Literal[
    "MEASURED_UNCERTAINTY", "PUBLISHED_BOUNDS", "EXPERT_ESTIMATE",
    "SCENARIO_ASSUMPTION",
]


class UncertaintySpec(BaseModel):
    """Uncertainty specification for a single parameter.

    Only parameters with explicit, sourced bounds may participate in
    Monte Carlo propagation. Never use arbitrary ±%.
    """
    model_config = ConfigDict(extra="forbid")
    parameter: str
    distribution: DistributionType
    lower: float
    upper: float
    mean: float | None = None
    std: float | None = None
    confidence: str = "UNKNOWN"
    source: str
    provenance: str  # must be one of UncertaintySource values
    notes: str | None = None


class MonteCarloResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameter: str
    sample_count: int
    p05: float | None = None
    p50: float | None = None
    p95: float | None = None
    mean: float | None = None
    std: float | None = None
    uncertainty_status: str = "NOT_QUANTIFIED"
    provenance: str = "NOT_QUANTIFIED"


def run_monte_carlo(specs: list[UncertaintySpec],
                    compute_fn,
                    n_samples: int = 1000,
                    seed: int = 42) -> dict[str, MonteCarloResult]:
    """Run Monte Carlo propagation for a set of uncertainty specs.

    Refuses to run if any required spec is missing.
    Uses a fixed seed for reproducibility.

    Args:
        specs: Parameter distributions (must be non-empty)
        compute_fn: callable(sample_dict) -> float
        n_samples: Number of Monte Carlo draws
        seed: Random seed for reproducibility

    Returns dict of {output_name: MonteCarloResult}
    """
    if not specs:
        return {"output": MonteCarloResult(
            parameter="output", sample_count=0,
            uncertainty_status="NOT_QUANTIFIED",
            provenance="No uncertainty specifications provided")}

    rng = random.Random(seed)
    outputs = []

    for _ in range(n_samples):
        sample = {}
        for spec in specs:
            if spec.distribution == "UNIFORM":
                v = rng.uniform(spec.lower, spec.upper)
            elif spec.distribution == "NORMAL":
                mean = spec.mean if spec.mean is not None else (spec.lower + spec.upper) / 2
                std = spec.std if spec.std is not None else (spec.upper - spec.lower) / 4
                v = rng.gauss(mean, std)
                v = max(spec.lower, min(spec.upper, v))
            elif spec.distribution == "TRIANGULAR":
                mode = spec.mean if spec.mean is not None else (spec.lower + spec.upper) / 2
                v = rng.triangular(spec.lower, spec.upper, mode)
            else:
                v = (spec.lower + spec.upper) / 2
            sample[spec.parameter] = v
        try:
            result = compute_fn(sample)
            if result is not None and math.isfinite(float(result)):
                outputs.append(float(result))
        except Exception:
            pass

    if len(outputs) < 10:
        return {"output": MonteCarloResult(
            parameter="output", sample_count=len(outputs),
            uncertainty_status="INSUFFICIENT_SAMPLES")}

    outputs_sorted = sorted(outputs)
    n = len(outputs_sorted)
    p05 = outputs_sorted[int(0.05 * n)]
    p50 = outputs_sorted[int(0.50 * n)]
    p95 = outputs_sorted[int(0.95 * n)]
    mean = sum(outputs) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in outputs) / n)

    provenance_values = list({s.provenance for s in specs})
    prov_str = ",".join(provenance_values)

    return {"output": MonteCarloResult(
        parameter="output",
        sample_count=n,
        p05=round(p05, 2),
        p50=round(p50, 2),
        p95=round(p95, 2),
        mean=round(mean, 2),
        std=round(std, 2),
        uncertainty_status="QUANTIFIED" if "SCENARIO_ASSUMPTION" not in prov_str else "SCENARIO_ONLY",
        provenance=prov_str,
    )}


NOT_QUANTIFIED_RESULT = MonteCarloResult(
    parameter="tension",
    sample_count=0,
    uncertainty_status="NOT_QUANTIFIED",
    provenance="NOT_QUANTIFIED",
)
