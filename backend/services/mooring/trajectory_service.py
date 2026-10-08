"""Buoy trajectory analysis and anchor position estimation.

IMPORTANT TERMINOLOGY:
- The anchor position is NEVER known from trajectory alone.
- Trajectory-derived anchor = ESTIMATED, not ACTUAL.
- "NOT_OFFERED_BY_SOURCE" means the current INCOIS endpoint does not expose GPS
  position as a real-time stream. The buoy has a physical position, but we only
  have the REGISTRY DEPLOYMENT position, not a live GPS track.

Trajectory quality:
  GOOD        >= 3 positions, reasonable time span
  DEGRADED    < 3 positions or very short time span
  INSUFFICIENT only 1 position or invalid
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from .models import TrajectoryPoint, TrajectoryAnalysis, DataProvenance

EARTH_RADIUS_M = 6371000.0
MIN_GOOD_POSITIONS = 3
MIN_GOOD_TIME_SPAN_S = 7200  # 2 hours


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters. Handles identical points correctly."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    a = min(1.0, max(0.0, a))  # guard against floating-point out of [0,1]
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 in degrees [0, 360).
    Returns 0.0 if points are identical.
    """
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def _parse_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _trajectory_quality(positions: list[dict]) -> str:
    n = len(positions)
    if n < 2:
        return "INSUFFICIENT"
    times = [_parse_timestamp(p.get("timestamp")) for p in positions]
    valid_times = [t for t in times if t is not None]
    if len(valid_times) >= 2:
        span_s = abs((max(valid_times) - min(valid_times)).total_seconds())
    else:
        span_s = 0
    if n >= MIN_GOOD_POSITIONS and span_s >= MIN_GOOD_TIME_SPAN_S:
        return "GOOD"
    return "DEGRADED"


def analyze_trajectory(buoy_id: str,
                       positions: list[dict],
                       anchor_lat: float | None = None,
                       anchor_lon: float | None = None) -> TrajectoryAnalysis:
    """Analyze buoy trajectory and estimate anchor reference point.

    IMPORTANT: The INCOIS OMNI system provides only registry deployment
    coordinates — not a real-time GPS track. All trajectory analysis using
    these coordinates compares the deployment position to itself, yielding
    zero displacement. This function is architecturally ready for real GPS
    when available.

    Returns ESTIMATED anchor (centroid) unless authoritative anchor is provided.
    Never labels the estimated point as ACTUAL.
    """
    quality = _trajectory_quality(positions)

    if not positions:
        return TrajectoryAnalysis(buoy_id=buoy_id)

    # Validate and filter coordinates
    valid_positions = []
    for p in positions:
        lat, lon = p.get("latitude"), p.get("longitude")
        if lat is None or lon is None:
            continue
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            continue
        valid_positions.append(p)

    if not valid_positions:
        return TrajectoryAnalysis(buoy_id=buoy_id)

    lats = [p["latitude"] for p in valid_positions]
    lons = [p["longitude"] for p in valid_positions]
    centroid_lat = sum(lats) / len(lats)
    centroid_lon = sum(lons) / len(lons)

    est_anchor_lat = anchor_lat if anchor_lat is not None else centroid_lat
    est_anchor_lon = anchor_lon if anchor_lon is not None else centroid_lon

    # Compute per-point metrics
    points = []
    max_excursion = 0.0
    for p in valid_positions:
        dist = haversine_m(est_anchor_lat, est_anchor_lon, p["latitude"], p["longitude"])
        bear = bearing_deg(est_anchor_lat, est_anchor_lon, p["latitude"], p["longitude"])
        max_excursion = max(max_excursion, dist)
        points.append(TrajectoryPoint(
            latitude=p["latitude"], longitude=p["longitude"],
            timestamp=p.get("timestamp", ""),
            distance_from_anchor_m=round(dist, 1),
            bearing_from_anchor_deg=round(bear, 1)))

    # Anchor provenance
    if anchor_lat is not None:
        anchor_prov = DataProvenance(
            source="NIOT",
            status="AUTHORITATIVE",
            confidence="HIGH",
            method="deployment_records",
            notes="Anchor position from NIOT deployment records")
    elif quality == "GOOD":
        anchor_prov = DataProvenance(
            source="GPS_TRAJECTORY",
            status="ESTIMATED",
            confidence="MEDIUM",
            method="trajectory_centroid",
            notes=(f"Anchor reference estimated from centroid of {len(valid_positions)} "
                   f"positions (quality={quality}). NOT an actual anchor position."))
    else:
        anchor_prov = DataProvenance(
            source="GPS_TRAJECTORY",
            status="ESTIMATED",
            confidence="LOW",
            method="trajectory_centroid",
            notes=(f"Anchor reference estimated from only {len(valid_positions)} positions "
                   f"(quality={quality}). Insufficient trajectory for reliable estimation."))

    return TrajectoryAnalysis(
        buoy_id=buoy_id,
        centroid_latitude=round(centroid_lat, 6),
        centroid_longitude=round(centroid_lon, 6),
        estimated_anchor_latitude=round(est_anchor_lat, 6),
        estimated_anchor_longitude=round(est_anchor_lon, 6),
        watch_circle_radius_m=round(max_excursion, 1),
        max_excursion_m=round(max_excursion, 1),
        points=points,
        provenance=anchor_prov)
