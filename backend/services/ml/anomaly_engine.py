"""Mooring health anomaly detection engine.

Uses unsupervised statistical anomaly detection because no labeled
physical failure data exists. Results are STATISTICAL ANOMALIES, not
confirmed engineering failures.

IMPORTANT DISTINCTIONS:
  statistical anomaly ≠ physical failure
  response anomaly ≠ mooring damage
  WATCH ≠ critical engineering state

Failure hypotheses are labeled as such — they require physical validation.
"""
from __future__ import annotations
import math
from pydantic import BaseModel, ConfigDict
from typing import Literal

AnomalyLabel = Literal[
    "NORMAL", "WATCH", "WARNING", "CRITICAL", "INSUFFICIENT_DATA"
]

FailureHypothesis = Literal[
    "LINE_OVERLOAD", "EXCESSIVE_OFFSET", "POSSIBLE_ANCHOR_DRAG",
    "POSSIBLE_LINE_DAMAGE", "SENSOR_FAILURE", "TELEMETRY_FAILURE",
    "MODEL_MISMATCH", "DATA_GAP",
]


class FailureHypothesisEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis: FailureHypothesis
    evidence: str
    confidence: str = "LOW"
    required_validation: str


class MooringHealthResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    station_id: str
    observation_timestamp: str
    data_anomaly: AnomalyLabel = "INSUFFICIENT_DATA"
    response_anomaly: AnomalyLabel = "INSUFFICIENT_DATA"
    engineering_risk: AnomalyLabel = "INSUFFICIENT_DATA"
    overall_health: AnomalyLabel = "INSUFFICIENT_DATA"
    hypotheses: list[FailureHypothesisEntry] = []
    notes: str | None = None


def assess_mooring_health(station_id: str,
                           observation_timestamp: str,
                           forcing_mode: str,
                           confidence: str,
                           risk_state: str,
                           utilization: float | None,
                           excursion_m: float | None,
                           solver_status: str) -> MooringHealthResult:
    """Compute mooring health from available indicators.

    Does NOT use ML model — pure rule-based screening assessment.
    Statistical anomaly detection (Isolation Forest etc.) deferred until
    sufficient time-series data exists.
    """
    hypotheses = []

    # Data anomaly
    if forcing_mode in ("NO_FORCING", "UNKNOWN"):
        data_anom: AnomalyLabel = "INSUFFICIENT_DATA"
    elif forcing_mode == "WIND_ONLY":
        data_anom = "WATCH"
        hypotheses.append(FailureHypothesisEntry(
            hypothesis="DATA_GAP",
            evidence="Current and wave forcing unavailable from source",
            confidence="HIGH",
            required_validation="Verify INCOIS data coverage for this station"))
    else:
        data_anom = "NORMAL"

    # Response anomaly (from solver)
    if solver_status in ("FAILED", "NOT_RUN"):
        resp_anom: AnomalyLabel = "INSUFFICIENT_DATA"
    elif risk_state == "CRITICAL":
        resp_anom = "CRITICAL"
    elif risk_state == "WARNING":
        resp_anom = "WARNING"
    elif risk_state == "WATCH":
        resp_anom = "WATCH"
    else:
        resp_anom = "NORMAL"

    # Engineering risk
    eng_risk = risk_state  # reuse the existing engineering risk

    # Hypotheses from indicators
    if utilization is not None and utilization > 0.6:
        hypotheses.append(FailureHypothesisEntry(
            hypothesis="LINE_OVERLOAD",
            evidence=f"Estimated utilization {utilization:.1%} exceeds warning threshold",
            confidence="LOW",
            required_validation="Verify MBL from authoritative deployment documentation"))

    if excursion_m is not None and excursion_m > 400:
        hypotheses.append(FailureHypothesisEntry(
            hypothesis="EXCESSIVE_OFFSET",
            evidence=f"Estimated excursion {excursion_m:.0f}m above watch threshold",
            confidence="LOW",
            required_validation="Compare with GPS trajectory or deployment watch-circle spec"))

    # Overall: worst of the three
    _sev = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3, "INSUFFICIENT_DATA": -1}
    concrete = [s for s in [data_anom, resp_anom, eng_risk]
                if s != "INSUFFICIENT_DATA"]
    if not concrete:
        overall = "INSUFFICIENT_DATA"
    else:
        overall = max(concrete, key=lambda s: _sev.get(s, 0))

    return MooringHealthResult(
        station_id=station_id,
        observation_timestamp=observation_timestamp,
        data_anomaly=data_anom,
        response_anomaly=resp_anom,
        engineering_risk=eng_risk,
        overall_health=overall,
        hypotheses=hypotheses,
    )
