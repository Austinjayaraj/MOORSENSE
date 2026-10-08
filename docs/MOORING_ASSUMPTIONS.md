# Mooring Digital Twin — Engineering Assumptions

## GEBCO Bathymetry

- Water depth is obtained from GEBCO (GEBCO_2026 grid, ~500m resolution)
- GEBCO is classified as INFERRED, NOT authoritative deployment survey data
- GEBCO itself states the grid should not be used for navigation or safety-at-sea purposes
- MoorSense uses GEBCO depth as a screening-level inferred input only
- Actual deployment depth at the anchor/fairlead may differ significantly from GEBCO
- To obtain the GEBCO subset: visit https://download.gebco.net/, select GEBCO_2026, bounding box S=5.57 W=66.45 N=19.50 E=95.07, save as backend/data/bathymetry/gebco_omni_indian_ocean.nc
- Pre-seeded depths for all 12 OMNI stations are embedded in bathymetry_service.py for offline operation

## Architecture

- OMNI buoys use single-point inverse-catenary mooring (OSICON-23, NIOT published design)
- Scope = 1.22 is a **reference/design constraint**, not individual deployment measurement
- Single mooring line per buoy (line_count = 1)

## Geometry

- Water depth from GEBCO bathymetry (~500m resolution) — actual depth at deployment may differ
- Line length = scope × depth (DERIVED, not measured)
- Simplified 3-segment model: upper rope (5%), compliant nylon (85%), anchor chain (10%)
- Segment proportions are reference estimates, not from deployment records

## Buoy Properties

- Diameter: 2.7 m (OMNI design class reference)
- Height: 3.2 m (OMNI design class reference)
- Mass: 2,500 kg (OMNI design class reference)
- Net buoyancy: ~24.5 kN (OMNI design class reference)
- Draft assumed as 50% of height
- Projected area derived from diameter (π·r²)

These are design-class values, NOT individual buoy measurements.

## Line Properties

- Rope: diameter 32mm, submerged weight 2.0 N/m, MBL 250 kN
- Chain: diameter 22mm, submerged weight 84.0 N/m, MBL 490 kN
- All are reference values from typical deep-sea mooring literature

## Forces

- Wind: standard quadratic drag (Cd = 1.2)
- Current: integrated along line depth with profile interpolation when available
- Waves: screening-level Morison (Cd = 1.0, Cm = 2.0) with linear wave theory
- Forces combined as 2D vectors (Fx, Fy), never scalar addition

## Solver

- Quasi-static catenary equilibrium
- Newton-Raphson iteration (max 100 iterations, tolerance 0.01 N)
- Length-weighted average submerged weight for multi-segment lines
- Anchor tension = horizontal component (catenary assumption)

## Provenance Status Taxonomy (Phase 3)

| Status | Meaning |
|--------|---------|
| MEASURED | Direct sensor observation (INCOIS telemetry only) |
| AUTHORITATIVE | From verified NIOT/OOS deployment records |
| REFERENCE | From published OMNI design documentation |
| INFERRED | From external dataset (e.g. GEBCO bathymetry) |
| DERIVED | Calculated from known quantities |
| MODELLED | From a numerical model |
| ESTIMATED | Statistical/trajectory estimate |
| ASSUMPTION | Engineering assumption with no verified source |
| UNAVAILABLE | Not obtainable from current sources |

## Phase 3 Audit Findings

**REFERENCE (published OMNI design):**
- Scope = 1.22 — OSICON-23 / NIOT published constraint
- Mooring type = INVERSE_CATENARY — OMNI design class
- Line count = 1 — single-point mooring
- Buoy diameter ≈ 2.7 m, height ≈ 3.2 m, mass ≈ 2500 kg — design-class values

**ASSUMPTION (no verified deployment source):**
- Rope MBL = 250 kN — unverified, typical deep-sea mooring literature
- Chain MBL = 490 kN — unverified, typical deep-sea mooring literature
- Rope submerged weight = 2.0 N/m — assumption
- Chain submerged weight = 84.0 N/m — assumption
- Segment split: 5% upper / 85% middle / 10% lower — assumption
- Pretension = 10% of net buoyancy (2453 N) — engineering assumption, not deployment setting
- Fairlead depth = 1.5 m — assumption

**INFERRED (GEBCO):**
- Water depth for all 12 OMNI stations — from GEBCO_2026 WMS
- GEBCO is NOT authoritative deployment survey data

**DERIVED:**
- Line length = GEBCO depth × scope 1.22

## NOT Modeled

- Dynamic amplification factors
- Fatigue accumulation
- Vortex-induced vibration (VIV)
- Full RAO-based hydrodynamic wave response
- Time-domain simulation
- Line-line interaction
- Snap loading
- Marine growth effects
- Corrosion degradation
- Anchor holding capacity verification

## Risk Thresholds

| Parameter | Watch | Warning | Critical |
|-----------|-------|---------|----------|
| Utilization | ≥ 0.40 | ≥ 0.60 | ≥ 0.80 |
| Safety factor | — | ≤ 2.0 | ≤ 1.5 |
| Excursion | ≥ 300m | ≥ 500m | — |

These are configurable and should be validated against industry standards.

## Data Quality Notes

- Missing wave data does NOT mean wave force = 0
- Missing current data does NOT mean current force = 0
- These are explicitly tracked as UNAVAILABLE, not zeroed
- Model confidence degrades when environmental inputs are incomplete
- Tension is always ESTIMATED (DERIVED), never MEASURED unless a physical sensor exists
