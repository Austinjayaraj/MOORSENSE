"""Mooring risk engine with configurable thresholds and separated risk dimensions.

Separates:
  DATA_RISK   — quality and completeness of input data
  MODEL_RISK  — confidence in the physics model configuration
  MOORING_RISK — estimated engineering state of the mooring

States: NORMAL / WATCH / WARNING / CRITICAL / INSUFFICIENT_DATA.
Thresholds must be configurable — do not hard-code engineering safety limits.
"""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict
from .models import RiskState, Confidence


class RiskThresholds:
    def __init__(self,
                 utilization_critical: float = 0.80,
                 utilization_warning: float = 0.60,
                 utilization_watch: float = 0.40,
                 excursion_warning_m: float = 500.0,
                 excursion_watch_m: float = 300.0,
                 safety_factor_critical: float = 1.5,
                 safety_factor_warning: float = 2.0):
        self.utilization_critical = utilization_critical
        self.utilization_warning = utilization_warning
        self.utilization_watch = utilization_watch
        self.excursion_warning_m = excursion_warning_m
        self.excursion_watch_m = excursion_watch_m
        self.safety_factor_critical = safety_factor_critical
        self.safety_factor_warning = safety_factor_warning


DEFAULT_THRESHOLDS = RiskThresholds()


class SeparatedRisk(BaseModel):
    """Three-dimensional risk assessment.

    data_status: quality of observational inputs
    model_status: reliability of the physics/configuration model
    engineering_status: estimated mooring engineering state
    overall_status: most severe of all dimensions
    """
    model_config = ConfigDict(extra="forbid")
    data_status: RiskState = "INSUFFICIENT_DATA"
    model_status: RiskState = "INSUFFICIENT_DATA"
    engineering_status: RiskState = "INSUFFICIENT_DATA"
    overall_status: RiskState = "INSUFFICIENT_DATA"
    data_notes: str | None = None
    model_notes: str | None = None
    engineering_notes: str | None = None


def assess_data_risk(telemetry_age_s: float | None,
                     forcing_mode: str,
                     thresholds: RiskThresholds = DEFAULT_THRESHOLDS) -> tuple[RiskState, str]:
    """Assess risk from data quality."""
    if telemetry_age_s is None:
        return "INSUFFICIENT_DATA", "No telemetry observation"
    if forcing_mode in ("NO_FORCING", "UNKNOWN"):
        return "INSUFFICIENT_DATA", "No environmental forcing available"
    if forcing_mode == "WIND_ONLY":
        note = "Wind-only: current and wave forcing unknown; total load may be significantly underestimated"
        return "WATCH", note
    if forcing_mode in ("PARTIAL_NO_CURRENT", "PARTIAL_NO_WAVES"):
        return "WATCH", f"Partial forcing ({forcing_mode}): some environmental components unknown"
    return "NORMAL", "Environmental forcing available"


def assess_model_risk(configuration_status: str,
                      confidence: Confidence,
                      solver_status: str) -> tuple[RiskState, str]:
    """Assess risk from model/configuration quality."""
    if solver_status in ("FAILED", "NOT_RUN"):
        return "INSUFFICIENT_DATA", f"Physics solver: {solver_status}"
    if configuration_status == "ASSUMPTION":
        return "WATCH", "Configuration is based on assumptions; results are screening-level"
    if configuration_status in ("REFERENCE", "PUBLISHED_REFERENCE"):
        return "WATCH", "Configuration is reference class; not deployment-verified"
    if confidence in ("LOW", "UNKNOWN"):
        return "WATCH", f"Model confidence is {confidence}"
    return "NORMAL", "Model and configuration acceptable"


def assess_engineering_risk(utilization: float | None,
                             safety_factor: float | None,
                             excursion_m: float | None,
                             solver_converged: bool,
                             thresholds: RiskThresholds = DEFAULT_THRESHOLDS) -> tuple[RiskState, str]:
    """Assess the engineering state of the mooring from physics outputs."""
    if not solver_converged:
        return "INSUFFICIENT_DATA", "Physics solver did not converge"
    if utilization is None and safety_factor is None:
        return "INSUFFICIENT_DATA", "Utilization unavailable (MBL unknown)"
    if utilization is not None and utilization >= thresholds.utilization_critical:
        return "CRITICAL", f"Estimated utilization {utilization:.1%} exceeds critical threshold"
    if safety_factor is not None and safety_factor <= thresholds.safety_factor_critical:
        return "CRITICAL", f"Estimated safety factor {safety_factor:.2f} below critical threshold"
    if utilization is not None and utilization >= thresholds.utilization_warning:
        return "WARNING", f"Estimated utilization {utilization:.1%} above warning threshold"
    if safety_factor is not None and safety_factor <= thresholds.safety_factor_warning:
        return "WARNING", f"Estimated safety factor {safety_factor:.2f} below warning threshold"
    if excursion_m is not None and excursion_m >= thresholds.excursion_warning_m:
        return "WARNING", f"Estimated excursion {excursion_m:.0f}m above warning threshold"
    if utilization is not None and utilization >= thresholds.utilization_watch:
        return "WATCH", f"Estimated utilization {utilization:.1%} above watch threshold"
    if excursion_m is not None and excursion_m >= thresholds.excursion_watch_m:
        return "WATCH", f"Estimated excursion {excursion_m:.0f}m above watch threshold"
    return "NORMAL", "Engineering state nominal"


_SEVERITY = {"NORMAL": 0, "WATCH": 1, "WARNING": 2,
             "CRITICAL": 3, "INSUFFICIENT_DATA": -1}


def _worst(*states: RiskState) -> RiskState:
    """Return the highest-severity risk state.

    INSUFFICIENT_DATA propagates if the data dimension has insufficient data
    (we cannot assess the overall risk). Otherwise returns the highest
    concrete risk state.
    """
    # If data dimension is INSUFFICIENT_DATA, overall is INSUFFICIENT_DATA
    if states and states[0] == "INSUFFICIENT_DATA":
        return "INSUFFICIENT_DATA"
    concrete = [s for s in states if s != "INSUFFICIENT_DATA"]
    if not concrete:
        return "INSUFFICIENT_DATA"
    return max(concrete, key=lambda s: _SEVERITY.get(s, -1))


def assess_risk(utilization: float | None = None,
                safety_factor: float | None = None,
                excursion_m: float | None = None,
                solver_converged: bool = False,
                thresholds: RiskThresholds = DEFAULT_THRESHOLDS) -> RiskState:
    """Backward-compatible single risk state (engineering dimension only)."""
    eng_risk, _ = assess_engineering_risk(
        utilization, safety_factor, excursion_m, solver_converged, thresholds)
    return eng_risk


def assess_separated_risk(telemetry_age_s: float | None,
                           forcing_mode: str,
                           configuration_status: str,
                           confidence: Confidence,
                           solver_status: str,
                           utilization: float | None = None,
                           safety_factor: float | None = None,
                           excursion_m: float | None = None,
                           thresholds: RiskThresholds = DEFAULT_THRESHOLDS) -> SeparatedRisk:
    """Compute three-dimensional separated risk assessment."""
    solver_converged = solver_status == "CONVERGED"

    d_state, d_note = assess_data_risk(telemetry_age_s, forcing_mode, thresholds)
    m_state, m_note = assess_model_risk(configuration_status, confidence, solver_status)
    e_state, e_note = assess_engineering_risk(
        utilization, safety_factor, excursion_m, solver_converged, thresholds)

    return SeparatedRisk(
        data_status=d_state,
        model_status=m_state,
        engineering_status=e_state,
        overall_status=_worst(d_state, m_state, e_state),
        data_notes=d_note,
        model_notes=m_note,
        engineering_notes=e_note,
    )
