"""Data confidence engine for mooring Digital Twin results.

Calculates per-dimension and overall confidence. Each dimension is independent.
The overall confidence cannot exceed LOW when any critical input is ASSUMPTION
or when key environmental data is unavailable.

Confidence levels:
  HIGH   — authoritative or directly measured, freshly received
  MEDIUM — reference/inferred, reasonably fresh data
  LOW    — assumed/estimated, aged data, partial environment
  UNKNOWN — no data at all for this dimension
"""
from .models import (
    Confidence, MooringConfiguration, EnvironmentalState, SolverStatus,
    ConfidenceBreakdown,
)


def _seg_provenance_worst(config: MooringConfiguration) -> str:
    """Return the worst provenance status among all line segments."""
    if not config.segments:
        return "UNKNOWN"
    statuses = [s.provenance.status for s in config.segments]
    priority = ["UNAVAILABLE", "ASSUMPTION", "UNKNOWN", "ESTIMATED",
                "INFERRED", "MODELLED", "DERIVED", "REFERENCE", "AUTHORITATIVE"]
    for worst in priority:
        if worst in statuses:
            return worst
    return "UNKNOWN"


def compute_confidence(config: MooringConfiguration,
                       env: EnvironmentalState,
                       solver_status: SolverStatus,
                       telemetry_age_seconds: float | None,
                       bathymetry_status: str | None = None) -> tuple[Confidence, ConfidenceBreakdown]:
    """Compute per-dimension and overall confidence.

    Returns (overall_confidence, ConfidenceBreakdown).
    """
    # ── Telemetry freshness ────────────────────────────────────────────────
    if telemetry_age_seconds is None:
        tel_conf: Confidence = "UNKNOWN"
    elif telemetry_age_seconds < 10800:
        tel_conf = "HIGH"
    elif telemetry_age_seconds < 21600:
        tel_conf = "MEDIUM"
    else:
        tel_conf = "LOW"

    # ── Bathymetry ─────────────────────────────────────────────────────────
    if config.water_depth and config.water_depth.value is not None:
        bathy_src_status = (config.water_depth.provenance.status
                            if config.water_depth.provenance else "UNKNOWN")
        if bathy_src_status == "AUTHORITATIVE":
            bathy_conf: Confidence = "HIGH"
        elif bathy_src_status == "INFERRED":
            bathy_conf = "MEDIUM"
        else:
            bathy_conf = "LOW"
    else:
        bathy_conf = "UNKNOWN"

    # ── Configuration geometry ─────────────────────────────────────────────
    if config.configuration_status == "AUTHORITATIVE":
        cfg_conf: Confidence = "HIGH"
    elif config.configuration_status == "REFERENCE" and config.has_minimum_geometry():
        cfg_conf = "MEDIUM"
    else:
        cfg_conf = "LOW"

    # ── Environmental data completeness ────────────────────────────────────
    has_wind = env.wind_speed_ms is not None
    has_current = env.current_speed_ms is not None
    has_waves = env.wave_height_m is not None
    if has_wind and has_current and has_waves:
        env_conf: Confidence = "HIGH"
    elif has_wind and (has_current or has_waves):
        env_conf = "MEDIUM"
    elif has_wind:
        env_conf = "LOW"  # wind-only: significant forcing may be unaccounted
    else:
        env_conf = "UNKNOWN"

    # ── Anchor position ────────────────────────────────────────────────────
    if config.anchor_latitude and config.anchor_latitude.provenance.status == "AUTHORITATIVE":
        anchor_conf: Confidence = "HIGH"
    elif config.anchor_latitude and config.anchor_latitude.provenance.status in ("ESTIMATED", "INFERRED"):
        anchor_conf = "MEDIUM"
    else:
        anchor_conf = "LOW"

    # ── Material properties ────────────────────────────────────────────────
    # ASSUMPTION provenance on segments must degrade confidence to LOW
    worst_seg = _seg_provenance_worst(config)
    if config.configuration_status == "AUTHORITATIVE":
        mat_conf: Confidence = "HIGH"
    elif worst_seg == "ASSUMPTION":
        mat_conf = "LOW"
    elif worst_seg in ("REFERENCE", "DERIVED"):
        mat_conf = "LOW"  # still LOW — not deployment-verified
    elif worst_seg == "UNAVAILABLE" or worst_seg == "UNKNOWN":
        mat_conf = "UNKNOWN"
    else:
        mat_conf = "LOW"

    # ── Physics convergence ────────────────────────────────────────────────
    if solver_status == "CONVERGED":
        phys_conf: Confidence = "HIGH"
    elif solver_status == "WARNING":
        phys_conf = "MEDIUM"
    elif solver_status == "NOT_RUN":
        phys_conf = "UNKNOWN"
    else:
        phys_conf = "LOW"

    breakdown = ConfidenceBreakdown(
        telemetry=tel_conf,
        bathymetry=bathy_conf,
        configuration=cfg_conf,
        environmental_data=env_conf,
        anchor_position=anchor_conf,
        material_properties=mat_conf,
        physics_convergence=phys_conf,
    )

    # ── Overall: conservative, honest ─────────────────────────────────────
    # Rules:
    # 1. Any UNKNOWN critical dimension → overall UNKNOWN
    # 2. ASSUMPTION material properties cap overall at LOW
    # 3. Wind-only environment caps overall at LOW (unaccounted forcing may dominate)
    # 4. Otherwise: minimum of all dimensions
    rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}
    all_confs = [tel_conf, bathy_conf, cfg_conf, env_conf, anchor_conf, mat_conf, phys_conf]
    values = [rank[c] for c in all_confs]
    min_val = min(values)

    if mat_conf == "LOW" and worst_seg == "ASSUMPTION":
        # Line properties are unverified assumptions — cap at LOW
        overall: Confidence = "LOW"
    elif env_conf == "LOW" and not has_current and not has_waves:
        # Wind-only: significant forcing components unknown
        overall = "LOW"
    elif min_val == 0:
        overall = "UNKNOWN"
    elif min_val == 1:
        overall = "LOW"
    elif min_val == 2:
        # Allow MEDIUM only if no ASSUMPTION-class material properties
        overall = "MEDIUM"
    else:
        overall = "HIGH"

    breakdown.overall = overall
    return overall, breakdown
