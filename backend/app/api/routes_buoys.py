import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

router = APIRouter()

def runtime(request): return request.app.state.buoy_runtime

def require_buoy(rt, buoy_id):
    if buoy_id not in rt.buoys: raise HTTPException(404, "Unknown buoy ID")

@router.get("/api/buoys")
async def buoys(request: Request):
    rt = runtime(request)
    return [rt.detail(buoy_id) for buoy_id in rt.buoys]

@router.get("/api/health/buoys")
async def buoy_health(request: Request):
    rt = runtime(request)
    diagnostics = getattr(rt.provider, "diagnostics", {})
    latest = max((o.timestamp for o in rt.cache.latest.values()), default=None)
    try:
        await rt.store.connect()
        count = await rt.store.pool.fetchval("SELECT count(*) FROM buoy_observations WHERE received_timestamp > now() - interval '1 hour'")
    except Exception: count = None
    return {"provider": "INCOIS", "providerReachable": diagnostics.get("providerReachable", False),
        "lastSuccessfulFetch": diagnostics.get("lastSuccessfulFetch"),
        "lastObservation": latest.isoformat() if latest else None, "stations": len(rt.buoys),
        "newObservationsLastHour": count, "kafka": rt.kafka_status == "CONNECTED",
        "persistence": rt.persistence_status == "CONNECTED",
        "websocket": bool(rt.manager.clients), "websocketClients": len(rt.manager.clients)}

@router.get("/api/buoys/debug/source")
async def source_debug(request: Request):
    rt = runtime(request)
    if not rt.config.buoy_debug_source_enabled or rt.config.environment != "development":
        raise HTTPException(404, "Not found")
    latest = max((o.timestamp for o in rt.cache.latest.values()), default=None)
    return {**getattr(rt.provider,"diagnostics",{}), "stations":len(rt.buoys),
        "latestObservation":latest.isoformat() if latest else None,
        "parameters":getattr(rt.provider,"parameter_status",{})}

@router.get("/api/buoys/{buoy_id}")
async def buoy(buoy_id: str, request: Request):
    rt = runtime(request)
    require_buoy(rt,buoy_id)
    return rt.detail(buoy_id)

@router.get("/api/buoys/{buoy_id}/parameters")
async def buoy_parameters(buoy_id: str, request: Request):
    """Per-parameter availability with latest value, unit, status, and source."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    detail = rt.detail(buoy_id)
    param_status = detail.get("parameterAvailability", {})
    telemetry = detail.get("telemetry") or {}
    obs_ts = detail.get("observationTimestamp")
    source = detail.get("source", "INCOIS")

    from services.buoy.telemetry_normalizer import (
        MET_FIELDS, WAVE_FIELDS, CURRENT_FIELDS, OCEAN_FIELDS,
    )
    all_known = {}
    for source_key, canon_key in MET_FIELDS.items():
        all_known.setdefault(source_key, ("meteorology", canon_key))
    for source_key, canon_key in WAVE_FIELDS.items():
        all_known.setdefault(source_key, ("waves", canon_key))
    for source_key, canon_key in CURRENT_FIELDS.items():
        all_known.setdefault(source_key, ("ocean", canon_key))
    for source_key, canon_key in OCEAN_FIELDS.items():
        all_known.setdefault(source_key, ("ocean", canon_key))

    from services.buoy.telemetry_normalizer import CANONICAL_PARAM_UNITS

    parameters = {}
    for source_key, (group, canon_key) in all_known.items():
        status = param_status.get(source_key, "UNKNOWN")
        metric = telemetry.get(group, {}).get(canon_key)
        val = metric.get("value") if isinstance(metric, dict) else None
        unit = metric.get("unit", "") if isinstance(metric, dict) else ""

        # Use canonical unit when available (protects against chart y-axis bugs)
        if source_key in CANONICAL_PARAM_UNITS:
            unit = CANONICAL_PARAM_UNITS[source_key]

        # Correct impossible states: if we have a value from profile promotion
        # (e.g. SST from water_temperature_1m) but the source key itself was
        # not a literal option name, mark it AVAILABLE not NOT_OFFERED.
        if val is not None and status in ("NOT_OFFERED", "UNKNOWN", "RESTRICTED"):
            status = "AVAILABLE"
        elif status == "AVAILABLE" and val is None:
            status = "NO_DATA"
        elif status not in ("AVAILABLE",) and val is None:
            pass  # keep existing status (NOT_OFFERED, RESTRICTED, SOURCE_UNAVAILABLE)

        parameters[source_key] = {
            "status": status,
            "canonical_key": canon_key,
            "group": group,
            "value": val if status == "AVAILABLE" else None,
            "unit": unit,
            "type": "measured" if status == "AVAILABLE" and val is not None else None,
            "last_observation": obs_ts if status == "AVAILABLE" and val is not None else None,
            "source": source if status == "AVAILABLE" else None,
        }

    # Profile parameters (depth-varying)
    profiles = telemetry.get("profiles", {})
    for profile_name, points in profiles.items():
        depths = [{"depth_m": p.get("depth"), "value": p.get("value"), "unit": p.get("unit")}
                  for p in (points or [])]
        parameters[f"{profile_name}_profile"] = {
            "status": "AVAILABLE" if depths else "NO_DATA",
            "group": "profiles",
            "type": "measured",
            "depths": depths,
            "last_observation": obs_ts,
            "source": source,
        }

    return {"buoy_id": buoy_id, "parameters": parameters, "observation_timestamp": obs_ts}

@router.get("/api/buoys/{buoy_id}/telemetry/latest")
async def telemetry_latest(buoy_id: str, request: Request):
    rt = runtime(request)
    require_buoy(rt,buoy_id)
    detail = rt.detail(buoy_id)
    obs_ts = detail.get("observationTimestamp")
    telemetry = detail.get("telemetry")
    if not obs_ts or not telemetry:
        return {"buoy_id": buoy_id, "status": "NO_DATA", "telemetry": None}

    # Extract source_epoch_ms from the cached observation's rawPayload
    cached_obs = rt.cache.latest.get(buoy_id)
    source_epoch_ms = None
    if cached_obs and cached_obs.rawPayload:
        source_epoch_ms = cached_obs.rawPayload.get("sourceEpochMs")

    measurements = []
    for group_name, group_data in telemetry.items():
        if group_name == "profiles":
            for param_name, points in (group_data or {}).items():
                for point in points:
                    measurements.append({
                        "parameter": param_name, "value": point.get("value"),
                        "unit": point.get("unit", ""), "depth_m": point.get("depth"),
                        "observation_timestamp": obs_ts,
                        "source": detail.get("source", "INCOIS"),
                        "source_epoch_ms": source_epoch_ms,
                        "received_timestamp": detail.get("receivedAt"),
                        "quality": "NOMINAL" if point.get("value") is not None else "MISSING",
                        "availability": "measured"
                    })
        else:
            for param_name, metric in (group_data or {}).items():
                measurements.append({
                    "parameter": param_name, "value": metric.get("value"),
                    "unit": metric.get("unit", ""), "depth_m": None,
                    "observation_timestamp": obs_ts,
                    "source": detail.get("source", "INCOIS"),
                    "source_epoch_ms": source_epoch_ms,
                    "received_timestamp": detail.get("receivedAt"),
                    "quality": "NOMINAL" if metric.get("value") is not None else "MISSING",
                    "availability": "measured"
                })
    return {"buoy_id": buoy_id, "observation_timestamp": obs_ts,
            "received_timestamp": detail.get("receivedAt"),
            "source": detail.get("source", "INCOIS"),
            "source_epoch_ms": source_epoch_ms,
            "freshness": detail.get("freshness"),
            "measurements": measurements, "status": "LATEST_AVAILABLE"}

@router.get("/api/buoys/{buoy_id}/telemetry/history")
async def telemetry_history(buoy_id: str, request: Request, start: datetime | None = None,
                            end: datetime | None = None, limit: int = Query(120, ge=1, le=1000)):
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise HTTPException(422, "Use timezone-aware dates with start <= end")
    try:
        observations = await rt.store.history(buoy_id, start, end, limit)
        return {"buoy_id": buoy_id, "observations": observations, "count": len(observations), "status": "AVAILABLE"}
    except Exception:
        return {"buoy_id": buoy_id, "observations": [], "count": 0, "status": "HISTORY_UNAVAILABLE"}

@router.get("/api/buoys/{buoy_id}/mooring")
async def mooring_config(buoy_id: str, request: Request):
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    config = await rt.get_mooring_config(buoy_id)
    return config

@router.get("/api/buoys/{buoy_id}/mooring/configuration")
async def mooring_configuration_dt(buoy_id: str, request: Request):
    """Digital Twin resolved mooring configuration with full provenance."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    buoy = rt.buoys[buoy_id]
    config = rt.config_resolver.resolve(buoy_id, buoy.latitude, buoy.longitude)
    return config.model_dump(mode="json")

@router.get("/api/buoys/{buoy_id}/mooring/response")
async def mooring_response_dt(buoy_id: str, request: Request):
    """Latest Digital Twin mooring response."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    response = rt.fleet_runner.get_response(buoy_id)
    if response:
        return response.model_dump(mode="json")
    buoy = rt.buoys[buoy_id]
    obs = rt.cache.latest.get(buoy_id)
    if not obs:
        return {"buoy_id": buoy_id, "solver_status": "NOT_RUN", "error": "No observation available"}
    from services.mooring.mooring_response import compute_mooring_response
    telemetry = obs.telemetry.model_dump(mode="json") if obs.telemetry else {}
    age = (datetime.now(timezone.utc) - obs.timestamp).total_seconds()
    result = compute_mooring_response(
        buoy_id=buoy_id, latitude=buoy.latitude, longitude=buoy.longitude,
        telemetry=telemetry, observation_timestamp=obs.timestamp.isoformat(),
        resolver=rt.config_resolver, telemetry_age_seconds=age)
    rt.fleet_runner.latest_responses[buoy_id] = result
    return result.model_dump(mode="json")

@router.get("/api/buoys/{buoy_id}/mooring/trajectory")
async def mooring_trajectory(buoy_id: str, request: Request):
    """Buoy trajectory analysis and estimated anchor position."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    buoy = rt.buoys[buoy_id]
    from services.mooring.trajectory_service import analyze_trajectory
    positions = [{"latitude": buoy.latitude, "longitude": buoy.longitude,
                  "timestamp": datetime.now(timezone.utc).isoformat()}]
    config = rt.fleet_runner.get_config(buoy_id)
    anchor_lat = config.anchor_latitude.value if config and config.anchor_latitude else None
    anchor_lon = config.anchor_longitude.value if config and config.anchor_longitude else None
    result = analyze_trajectory(buoy_id, positions, anchor_lat, anchor_lon)
    return result.model_dump(mode="json")

@router.get("/api/mooring/fleet")
async def mooring_fleet(request: Request):
    """Fleet-wide Digital Twin summary for all accessible buoys."""
    rt = runtime(request)
    results = rt.run_fleet_digital_twin()
    return [r.model_dump(mode="json") for r in results]

@router.get("/api/buoys/{buoy_id}/mooring/status")
async def mooring_status(buoy_id: str, request: Request):
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    status = await rt.get_mooring_status(buoy_id)
    return status

@router.get("/api/buoys/{buoy_id}/mooring/tension")
async def mooring_tension(buoy_id: str, request: Request):
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    tension = await rt.get_mooring_tension(buoy_id)
    return tension

@router.get("/api/buoys/{buoy_id}/digital-twin")
async def digital_twin(buoy_id: str, request: Request):
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    detail = rt.detail(buoy_id)
    config = await rt.get_mooring_config(buoy_id)
    tension = await rt.get_mooring_tension(buoy_id)
    estimate = rt.latest_estimates.get(buoy_id)
    telemetry = detail.get("telemetry") or {}
    obs_ts = detail.get("observationTimestamp")

    has_mooring = config.get("availability") == "STATIC"
    has_estimate = tension.get("model_status") not in (None, "INSUFFICIENT_CONFIGURATION")

    derived = {}
    if estimate:
        ef = estimate.environmental_forces
        derived = {
            "wind_force": {"value": ef.wind_force_N, "unit": "N", "type": "derived", "model_level": ef.model_level} if ef.wind_force_N is not None else {"value": None, "status": "UNAVAILABLE"},
            "current_force": {"value": ef.current_force_N, "unit": "N", "type": "derived", "model_level": ef.model_level} if ef.current_force_N is not None else {"value": None, "status": "UNAVAILABLE"},
            "wave_force": {"value": ef.wave_force_N, "unit": "N", "type": "derived", "model_level": "screening"} if ef.wave_force_N is not None else {"value": None, "status": "UNAVAILABLE"},
            "resultant_force": {"value": ef.total_horizontal_force_N, "unit": "N", "direction_deg": ef.total_force_direction_deg, "type": "derived"} if ef.total_horizontal_force_N is not None else {"value": None, "status": "UNAVAILABLE"},
            "line_tensions": [l.model_dump(mode="json") for l in estimate.lines],
            "max_tension": {"value": estimate.max_tension_N, "unit": "N", "type": "derived", "model": "quasi_static_catenary", "model_level": "screening"} if estimate.max_tension_N is not None else {"value": None, "status": "INSUFFICIENT_CONFIGURATION"},
            "max_utilization": estimate.max_utilization,
            "risk_level": estimate.risk_level,
            "model_status": estimate.model_status,
            "calculated_at": estimate.calculated_at,
        }

    return {
        "buoy_id": buoy_id,
        "buoy": {
            "id": detail.get("id"), "name": detail.get("name"),
            "latitude": detail.get("latitude"), "longitude": detail.get("longitude"),
            "type": detail.get("type"), "status": detail.get("status"),
            "source": detail.get("source"),
        },
        "telemetry": {
            "meteorology": telemetry.get("meteorology", {}),
            "waves": telemetry.get("waves", {}),
            "currents": {k: v for k, v in telemetry.get("ocean", {}).items() if k in ("currentSpeed", "currentDirection")},
            "ocean": {k: v for k, v in telemetry.get("ocean", {}).items() if k not in ("currentSpeed", "currentDirection")},
            "profiles": telemetry.get("profiles", {}),
            "observation_timestamp": obs_ts,
            "freshness": detail.get("freshness"),
        },
        "mooring_configuration": config,
        "derived": derived if derived else {
            "status": "INSUFFICIENT_CONFIGURATION",
            "reason": "Authoritative mooring configuration required from NIOT/OOS deployment documentation",
        },
        "availability": {
            "telemetry": "MEASURED",
            "mooring_configuration": "STATIC_AUTHORITATIVE" if has_mooring else "UNAVAILABLE",
            "environmental_forces": "DERIVED" if has_estimate else "UNAVAILABLE",
            "mooring_tension": "DERIVED" if has_estimate and tension.get("model_status") == "VALIDATED_INPUTS" else "UNAVAILABLE",
            "parameter_availability": detail.get("parameterAvailability", {}),
        },
        "provenance": {
            "telemetry_source": detail.get("source", "INCOIS"),
            "observation_timestamp": obs_ts,
            "received_timestamp": detail.get("receivedAt"),
            "mooring_source": config.get("source"),
            "mooring_document": config.get("source_document"),
            "mooring_verified": config.get("verified", False),
        },
        "limitations": [
            "Quasi-static catenary model — no dynamic amplification or fatigue analysis",
            "Screening-level wave forcing — simplified Morison estimate, not RAO-based",
            "Equal load sharing across mooring lines",
            "Single-segment line model",
            "No vortex-induced vibration (VIV) modeling",
            "Estimated tension is DERIVED, not measured by a physical sensor",
        ] if has_estimate else [
            "Mooring analysis unavailable — requires authoritative NIOT deployment configuration",
            "All mooring engineering fields (water depth, line properties, anchor position) are currently UNAVAILABLE",
        ],
    }

@router.get("/api/buoys/{buoy_id}/mooring/capabilities")
async def mooring_capabilities(buoy_id: str, request: Request):
    """Per-parameter environmental capability profile for this station."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    from services.mooring.station_capabilities import build_capability_profile
    param_status = getattr(rt.provider, "parameter_status", {}).get(buoy_id, {})
    profile = build_capability_profile(buoy_id, param_status)
    return {**profile.model_dump(mode="json"),
            "environmental_completeness": profile.environmental_completeness()}

@router.get("/api/buoys/{buoy_id}/mooring/provenance")
async def mooring_provenance(buoy_id: str, request: Request):
    """Full provenance breakdown for this station's mooring configuration."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    buoy = rt.buoys[buoy_id]
    config = rt.config_resolver.resolve(buoy_id, buoy.latitude, buoy.longitude)
    response = rt.fleet_runner.get_response(buoy_id)
    return {
        "buoy_id": buoy_id,
        "water_depth": config.water_depth.model_dump(mode="json") if config.water_depth else None,
        "line_length": config.total_line_length.model_dump(mode="json") if config.total_line_length else None,
        "scope": config.scope.model_dump(mode="json") if config.scope else None,
        "pretension": config.pretension_n.model_dump(mode="json") if config.pretension_n else None,
        "segment_provenance": [
            {"name": s.name, "provenance": s.provenance.model_dump(mode="json")}
            for s in config.segments
        ],
        "configuration_status": config.configuration_status,
        "telemetry": {
            "observation_timestamp": rt.cache.detail(buoy).get("observationTimestamp"),
            "source": rt.cache.detail(buoy).get("source"),
        },
        "requires_authoritative_mooring_configuration": True,
        "model_disclaimer": (
            "Screening-level model estimate. Not a certified engineering analysis. "
            "Does not replace authoritative NIOT deployment documentation, "
            "dynamic analysis, geotechnical analysis, or physical tension measurements."
        ),
    }

@router.get("/api/mooring/model/version")
async def model_version(request: Request):
    """Return the current model version stack."""
    from services.mooring.versioned_config import model_version_metadata
    return model_version_metadata()

@router.post("/api/buoys/{buoy_id}/mooring/recalculate")
async def mooring_recalculate(buoy_id: str, request: Request):
    """Manually trigger a mooring Digital Twin recalculation for this station."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    buoy = rt.buoys[buoy_id]
    obs = rt.cache.latest.get(buoy_id)
    if not obs:
        raise HTTPException(404, "No observation available for this station")
    from services.mooring.mooring_response import compute_mooring_response
    telemetry = obs.telemetry.model_dump(mode="json") if obs.telemetry else {}
    age = (datetime.now(timezone.utc) - obs.timestamp).total_seconds()
    result = compute_mooring_response(
        buoy_id=buoy_id, latitude=buoy.latitude, longitude=buoy.longitude,
        telemetry=telemetry, observation_timestamp=obs.timestamp.isoformat(),
        resolver=rt.config_resolver, telemetry_age_seconds=age)
    rt.fleet_runner.latest_responses[buoy_id] = result
    return {"status": "recalculated", "model_timestamp": result.model_timestamp,
            "solver_status": result.solver_status, "confidence": result.confidence}

@router.get("/api/buoys/{buoy_id}/mooring/health")
async def mooring_health(buoy_id: str, request: Request):
    """Mooring health assessment for this station."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    from services.ml.anomaly_engine import assess_mooring_health
    response = rt.fleet_runner.get_response(buoy_id)
    if not response:
        return {"buoy_id": buoy_id, "overall_health": "INSUFFICIENT_DATA",
                "notes": "No mooring response computed yet"}
    result = assess_mooring_health(
        station_id=buoy_id,
        observation_timestamp=response.observation_timestamp,
        forcing_mode=response.forcing_mode,
        confidence=response.confidence,
        risk_state=response.risk_state,
        utilization=response.utilization,
        excursion_m=response.horizontal_excursion_m,
        solver_status=response.solver_status)
    return result.model_dump(mode="json")

@router.get("/api/buoys/{buoy_id}/mooring/validation")
async def mooring_validation(buoy_id: str, request: Request):
    """Physical validation status for this station's mooring model."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    from services.mooring.validation import VALIDATION_STATUS_NO_DATA, DISPLACEMENT_VALIDATION_STATUS
    return {
        "buoy_id": buoy_id,
        "tension_validation": VALIDATION_STATUS_NO_DATA.model_dump(mode="json"),
        "displacement_validation": DISPLACEMENT_VALIDATION_STATUS.model_dump(mode="json"),
        "overall_validation_status": "NOT_VALIDATED",
        "notes": ("No physical tension measurements or validated displacement records "
                  "are available. Model has not been validated against deployment observations."),
    }

@router.get("/api/buoys/{buoy_id}/mooring/uncertainty")
async def mooring_uncertainty(buoy_id: str, request: Request):
    """Uncertainty quantification status for this station."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    from services.mooring.uncertainty import NOT_QUANTIFIED_RESULT
    return {
        "buoy_id": buoy_id,
        "tension_uncertainty": NOT_QUANTIFIED_RESULT.model_dump(mode="json"),
        "overall_uncertainty_status": "NOT_QUANTIFIED",
        "notes": ("No defensible uncertainty bounds exist for MBL, pretension, "
                  "or water depth precision. Monte Carlo analysis is available "
                  "but requires explicit, sourced parameter distributions."),
    }

@router.get("/api/buoys/{buoy_id}/mooring/sensitivity")
async def mooring_sensitivity(buoy_id: str, request: Request):
    """Sensitivity analysis availability for this station."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    return {
        "buoy_id": buoy_id,
        "status": "AVAILABLE_VIA_API",
        "notes": ("Sensitivity analysis can be run by supplying parameter ranges "
                  "via POST /api/buoys/{id}/mooring/sensitivity. "
                  "Scenario ranges must be explicitly provided — no default ranges are assumed."),
        "available_parameters": ["scope", "water_depth", "submerged_weight_per_m",
                                  "breaking_strength_n", "pretension_n"],
    }

@router.get("/api/mooring/fleet/health")
async def fleet_health(request: Request):
    """Fleet-wide mooring health summary."""
    rt = runtime(request)
    from services.ml.anomaly_engine import assess_mooring_health
    results = []
    for buoy_id in rt.buoys:
        response = rt.fleet_runner.get_response(buoy_id)
        if not response:
            results.append({"buoy_id": buoy_id, "overall_health": "INSUFFICIENT_DATA"})
            continue
        try:
            h = assess_mooring_health(
                station_id=buoy_id,
                observation_timestamp=response.observation_timestamp,
                forcing_mode=response.forcing_mode,
                confidence=response.confidence,
                risk_state=response.risk_state,
                utilization=response.utilization,
                excursion_m=response.horizontal_excursion_m,
                solver_status=response.solver_status)
            results.append({
                "buoy_id": buoy_id,
                "overall_health": h.overall_health,
                "data_anomaly": h.data_anomaly,
                "engineering_risk": h.engineering_risk,
                "confidence": response.confidence,
                "forcing_mode": response.forcing_mode,
            })
        except Exception:
            results.append({"buoy_id": buoy_id, "overall_health": "INSUFFICIENT_DATA"})
    return {"fleet": results, "total": len(results)}

@router.get("/api/buoys/{buoy_id}/mooring/history")
async def mooring_history(buoy_id: str, request: Request,
                          start: datetime | None = None,
                          end: datetime | None = None,
                          limit: int = Query(120, ge=1, le=1000)):
    """Historical mooring replay results from PostgreSQL."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise HTTPException(422, "Use timezone-aware dates with start <= end")
    from services.replay.replay_store import ReplayStore
    store = ReplayStore(rt.store)
    try:
        rows = await store.query(buoy_id, start, end, limit)
        return {"buoy_id": buoy_id, "results": rows,
                "count": len(rows), "status": "AVAILABLE"}
    except Exception as exc:
        raise HTTPException(503, f"PostgreSQL unavailable: {type(exc).__name__}")

@router.post("/api/buoys/{buoy_id}/mooring/replay")
async def mooring_replay_post(buoy_id: str, request: Request):
    """Trigger a historical replay over a time range.

    Body: {"start": "ISO timestamp", "end": "ISO timestamp"}

    Requires PostgreSQL. Raises 503 if DB unavailable — never silently falls back.
    """
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    body = await request.json()
    try:
        start = datetime.fromisoformat(body["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(body["end"].replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, f"Invalid request: {exc}")
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise HTTPException(422, "start must be before end, both timezone-aware")

    # Load observations from PostgreSQL history
    buoy = rt.buoys[buoy_id]
    try:
        obs_list = await rt.store.history(buoy_id, start, end, limit=1000)
    except Exception as exc:
        raise HTTPException(503, f"PostgreSQL unavailable: {type(exc).__name__}")

    if not obs_list:
        return {"status": "NO_DATA", "buoy_id": buoy_id,
                "observation_count": 0, "message": "No observations in range"}

    from services.replay.replay_runner import ReplayObservation
    from services.replay.replay_service import ReplayService
    svc = ReplayService(rt.store, rt.config_resolver)

    observations = []
    for raw in obs_list:
        ts_str = raw.get("timestamp") or raw.get("observationTimestamp")
        if not ts_str:
            continue
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        telemetry = raw.get("telemetry", {})
        observations.append(ReplayObservation(
            station_id=buoy_id, observation_timestamp=ts,
            telemetry=telemetry, source=raw.get("source", "INCOIS")))

    try:
        result = await svc.run_replay(buoy_id, start, end, observations)
        return result
    except Exception as exc:
        raise HTTPException(503, f"Replay failed: {type(exc).__name__}: {exc}")

@router.get("/api/buoys/{buoy_id}/mooring/replay/{run_id}")
async def mooring_replay_results(buoy_id: str, run_id: str, request: Request,
                                  limit: int = Query(200, ge=1, le=1000)):
    """Get results for a specific replay run."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    from services.replay.replay_service import ReplayService
    svc = ReplayService(rt.store, rt.config_resolver)
    try:
        run = await svc.get_run(run_id)
        if not run or run["station_id"] != buoy_id:
            raise HTTPException(404, "Replay run not found")
        results = await svc.get_results(run_id, limit)
        return {"run_id": run_id, "station_id": buoy_id,
                "results": results, "count": len(results)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, f"PostgreSQL unavailable: {type(exc).__name__}")

@router.get("/api/buoys/{buoy_id}/mooring/replay/{run_id}/summary")
async def mooring_replay_summary(buoy_id: str, run_id: str, request: Request):
    """Summary statistics for a completed replay run."""
    rt = runtime(request)
    require_buoy(rt, buoy_id)
    from services.replay.replay_service import ReplayService
    svc = ReplayService(rt.store, rt.config_resolver)
    try:
        summary = await svc.get_summary(run_id)
        return summary
    except Exception as exc:
        raise HTTPException(503, f"PostgreSQL unavailable: {type(exc).__name__}")

@router.get("/api/buoys/{buoy_id}/history")
async def history(buoy_id: str, request: Request, start: datetime | None = None,
                  end: datetime | None = None, limit: int = Query(120,ge=1,le=1000)):
    rt = runtime(request)
    require_buoy(rt,buoy_id)
    end = end or datetime.now(timezone.utc)
    if start is None and end is not None and buoy_id in rt.cache.latest:
        # Recent source observations, even when the provider itself is stale.
        end = min(end, rt.cache.latest[buoy_id].timestamp)
    start = start or end-timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise HTTPException(422,"Use timezone-aware dates with start <= end")
    try:
        observations = await rt.store.history(buoy_id,start,end,limit)
        return {"observations": observations,"status": "AVAILABLE"}
    except Exception:
        return {"observations": [],"status": "HISTORY UNAVAILABLE"}

@router.websocket("/ws/buoys")
async def buoy_websocket(ws: WebSocket):
    rt = ws.app.state.buoy_runtime
    origin = ws.headers.get("origin")
    if origin and origin not in rt.config.buoy_ws_allowed_origins.split(","):
        await ws.close(code=1008)
        return
    await ws.accept()
    rt.manager.add(ws)
    client = rt.manager.clients[ws]
    async def sender():
        while True:
            try:
                event = await asyncio.wait_for(client["queue"].get(),timeout=15)
                if event["buoyId"] == client["buoyId"]:
                    await asyncio.wait_for(ws.send_json(event),timeout=10)
            except asyncio.TimeoutError:
                if client["buoyId"]:
                    state = rt.detail(client["buoyId"])
                    await asyncio.wait_for(ws.send_json({"type": "buoy_status", "buoyId": client["buoyId"],
                        "freshness": state["freshness"], "providerStatus": state["providerStatus"],
                        "error": state["error"], "pipeline": state["pipeline"]}),timeout=10)
    send_task = asyncio.create_task(sender())
    try:
        while True:
            receive_task = asyncio.create_task(ws.receive_json())
            done,_ = await asyncio.wait([receive_task,send_task],return_when=asyncio.FIRST_COMPLETED)
            if send_task in done:
                receive_task.cancel()
                with suppress(asyncio.CancelledError): await receive_task
                await send_task
            try: message = await receive_task
            except ValueError:
                await ws.close(code=1008)
                break
            if not isinstance(message,dict):
                await ws.close(code=1008)
                break
            if message.get("type") == "unsubscribe": client["buoyId"] = None
            elif message.get("type") == "subscribe":
                buoy_id = message.get("buoyId")
                if not isinstance(buoy_id,str) or buoy_id not in rt.buoys:
                    await ws.close(code=1008)
                    break
                client["buoyId"] = buoy_id
                while not client["queue"].empty(): client["queue"].get_nowait()
                client["queue"].put_nowait({"type":"buoy_state","buoyId":buoy_id,"buoy":rt.detail(buoy_id)})
    except (WebSocketDisconnect,RuntimeError,asyncio.TimeoutError): pass
    finally:
        send_task.cancel()
        with suppress(asyncio.CancelledError,RuntimeError,WebSocketDisconnect,asyncio.TimeoutError): await send_task
        rt.manager.remove(ws)
