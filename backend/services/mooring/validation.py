"""Physical validation framework for mooring Digital Twin.

Supports comparison of model outputs against physical measurements.
All measurement fields default to None — no fabricated values.

Current state: NOT_VALIDATED for all stations (no physical measurements available).
"""
from __future__ import annotations
import math
from pydantic import BaseModel, ConfigDict


class MeasuredTension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tension_n: float
    sensor_id: str | None = None
    timestamp: str | None = None
    quality: str = "UNKNOWN"
    source: str = "PHYSICAL_SENSOR"


class MeasuredLineAngle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    angle_deg: float
    sensor_id: str | None = None
    timestamp: str | None = None
    quality: str = "UNKNOWN"
    source: str = "PHYSICAL_SENSOR"


class MeasuredDisplacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    displacement_m: float
    bearing_deg: float | None = None
    sensor_id: str | None = None
    timestamp: str | None = None
    quality: str = "UNKNOWN"
    source: str = "GPS"


class ValidationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_count: int = 0
    absolute_error: float | None = None
    relative_error: float | None = None
    bias: float | None = None
    mae: float | None = None
    rmse: float | None = None
    validation_status: str = "NOT_VALIDATED"
    notes: str | None = None


def compare_model_measurement(modelled: list[float],
                               measured: list[float]) -> ValidationMetrics:
    """Compare model outputs against physical measurements.

    Both lists must be the same length and contain matched pairs.
    Returns NOT_VALIDATED if either list is empty.
    """
    if not modelled or not measured or len(modelled) != len(measured):
        return ValidationMetrics(
            validation_status="NOT_VALIDATED",
            notes="Insufficient matched pairs")

    n = len(modelled)
    errors = [m - p for m, p in zip(measured, modelled)]
    abs_errors = [abs(e) for e in errors]
    mae = sum(abs_errors) / n
    rmse = math.sqrt(sum(e ** 2 for e in errors) / n)
    bias = sum(errors) / n
    mean_abs = sum(abs(m) for m in measured) / n
    rel_error = mae / mean_abs if mean_abs > 0 else None

    return ValidationMetrics(
        sample_count=n,
        absolute_error=round(errors[-1], 3) if errors else None,
        relative_error=round(rel_error, 4) if rel_error is not None else None,
        bias=round(bias, 3),
        mae=round(mae, 3),
        rmse=round(rmse, 3),
        validation_status="VALIDATED" if n >= 3 else "INSUFFICIENT_SAMPLES",
    )


VALIDATION_STATUS_NO_DATA = ValidationMetrics(
    validation_status="NOT_VALIDATED",
    notes="No physical measurements available. Physical tension sensor absent.")

DISPLACEMENT_VALIDATION_STATUS = ValidationMetrics(
    validation_status="NOT_IMPLEMENTED",
    notes=("Displacement validation requires a physics model that predicts "
           "buoy offset from a complete force-balance equilibrium. "
           "Current implementation predicts excursion from catenary geometry; "
           "direct GPS-vs-model comparison is not yet implemented."))
