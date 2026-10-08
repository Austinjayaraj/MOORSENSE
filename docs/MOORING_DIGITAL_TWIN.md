# Mooring Digital Twin Architecture

## Pipeline

```
INCOIS REAL TELEMETRY
        +
GEBCO BATHYMETRY
        +
OMNI/NIOT REFERENCE MOORING ARCHITECTURE
        ↓
MooringConfigResolver
        ↓
EnvironmentalForceEngine
        ↓
CatenarySolver (inverse catenary, quasi-static)
        ↓
RiskEngine + ConfidenceEngine
        ↓
MooringResponse
        ↓
PostgreSQL + WebSocket + React
```

## Data Provenance

Every quantity carries one of:

| Status | Meaning |
|--------|---------|
| MEASURED | Directly observed by buoy sensors (INCOIS telemetry) |
| AUTHORITATIVE | From NIOT/OOS deployment records |
| REFERENCE | From published OMNI design documentation |
| INFERRED | From external datasets (e.g. GEBCO bathymetry) |
| DERIVED | Calculated by MoorSense physics from other inputs |
| MODELLED | From numerical ocean/atmospheric models |
| ESTIMATED | From trajectory/statistical estimation |
| UNAVAILABLE | Not obtainable from current sources |

## OMNI Reference Architecture

Published NIOT/INCOIS material (OSICON-23) establishes:
- Single-point mooring
- Inverse catenary / S-mooring geometry
- Scope ≈ 1.22

This is a **design reference**, not proof of every buoy's current deployed dimensions.

## Configuration Resolution

1. Check authoritative NIOT deployment database
2. If found → use exact values, status = AUTHORITATIVE
3. Otherwise → bathymetry + OMNI scope → reference configuration
   - Water depth: INFERRED from GEBCO
   - Line length: DERIVED from scope × depth
   - Segments: REFERENCE from OMNI design class
   - All values explicitly marked with provenance

## Bathymetry

- Source: GEBCO (local netCDF tile or WMS lookup)
- Resolution: ~500m grid
- Cached per buoy_id + rounded coordinates
- Status: INFERRED (actual deployment depth may differ)

## Environmental Forces

- Wind: F = ½ρ·Cd·A·V² (MEASURED wind from INCOIS)
- Current: Integrated along mooring line with profile interpolation
- Waves: Screening-level Morison (drag + inertia) with linear wave theory
- All forces decomposed as (Fx, Fy) vectors, never scalar-added

## Catenary Solver

Quasi-static Newton-Raphson solver supporting:
- Multi-segment lines with different material properties
- Seabed contact and friction
- Pretension
- Returns: fairlead/anchor tension, line angle, excursion, convergence

## Risk States

| State | Condition |
|-------|-----------|
| NORMAL | All indicators within normal range |
| WATCH | Elevated utilization or excursion |
| WARNING | Utilization ≥ 0.6 or SF ≤ 2.0 |
| CRITICAL | Utilization ≥ 0.8 or SF ≤ 1.5 |
| INSUFFICIENT_DATA | Solver failed or missing critical inputs |

Thresholds are configurable.

## Confidence

Computed from: telemetry freshness, environmental data completeness, mooring geometry quality, anchor position confidence, material properties, physics convergence.

## Limitations

1. Quasi-static analysis only — no dynamic amplification or fatigue
2. Screening-level Morison wave forcing — not full hydrodynamic RAO
3. Equal load sharing (single-point mooring = 1 line)
4. Reference material properties where authoritative data unavailable
5. No VIV modeling
6. No time-domain simulation
7. Tension is ESTIMATED, not measured by a physical sensor

## API Endpoints

- `GET /api/buoys/{id}/mooring/configuration` — resolved config with provenance
- `GET /api/buoys/{id}/mooring/response` — latest Digital Twin result
- `GET /api/buoys/{id}/mooring/trajectory` — position analysis
- `GET /api/mooring/fleet` — fleet-wide summary

## Files

```
backend/services/mooring/
    models.py              — Data models with provenance
    bathymetry_service.py  — GEBCO depth lookup
    config_resolver.py     — OMNI reference + authoritative resolution
    trajectory_service.py  — Buoy excursion and anchor estimation
    environmental_forces.py — Wind/current/wave force engine
    catenary_solver.py     — Quasi-static inverse catenary solver
    mooring_response.py    — Full pipeline orchestrator
    risk_engine.py         — Configurable risk state machine
    confidence.py          — Multi-factor confidence calculator
    fleet_runner.py        — Fleet-wide Digital Twin batch runner
```
