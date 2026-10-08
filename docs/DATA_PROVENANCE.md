# Data Provenance

Every value in MoorSense carries explicit provenance. This document explains the taxonomy.

## ProvenanceStatus Values

| Status | Meaning | Example |
|--------|---------|---------|
| MEASURED | Direct sensor observation | INCOIS wind speed, air temperature |
| AUTHORITATIVE | From verified NIOT/OOS deployment records | Station-specific mooring specs (when available) |
| REFERENCE | From published OMNI design documentation | Scope 1.22 (OSICON-23) |
| INFERRED | Derived from external datasets | GEBCO_2026 water depth |
| DERIVED | Calculated from other known quantities | Line length = depth × scope |
| MODELLED | From a numerical model | (future: HYCOM currents) |
| ESTIMATED | Statistical/trajectory estimate | Anchor position from buoy centroid |
| ASSUMPTION | Engineering assumption with no verified source | MBL 250 kN, segment proportions |
| UNAVAILABLE | Not obtainable from current sources | Actual pretension |

## Telemetry Provenance

All INCOIS OMNI observations are MEASURED.
Source: `https://www.incois.gov.in/site/datainfo/moored_omnidata_stock.jsp`
Timestamps: UTC (validated by `useUTC: true` contract)
Units: Canonical (°C, hPa, m/s, PSU — chart y-axis is not trusted)

## Bathymetry Provenance

GEBCO_2026 grid (~15 arc-second, ~500m resolution)
Status: INFERRED
Confidence: MEDIUM
Notes: Not a deployment survey. GEBCO states grid should not be used for
navigation or safety-at-sea.

## Configuration Provenance Chain

```
INCOIS OMNI telemetry          → MEASURED
GEBCO depth                    → INFERRED
Line length = scope × depth    → DERIVED
Scope 1.22                     → REFERENCE (OSICON-23)
MBL, diameters, weights        → ASSUMPTION (unverified)
Pretension                     → ASSUMPTION (10% net buoyancy estimate)
```

## Physics Output Provenance

All physics outputs are DERIVED or MODELLED:
- Environmental forces: DERIVED from measured telemetry + reference geometry
- Catenary tension: MODELLED (quasi-static screening-level estimate)
- Utilization: DERIVED from modelled tension ÷ assumed MBL
- Safety factor: DERIVED from assumed MBL ÷ modelled tension

**Never label catenary solver output as MEASURED.**

## Confidence Levels

| Level | Meaning |
|-------|---------|
| HIGH | Authoritative source, fresh data, validated |
| MEDIUM | Reference source or inferred from reliable dataset |
| LOW | Assumption or aged data |
| UNKNOWN | No data available |

## Traceability

Every API response includes provenance fields. The digital-twin endpoint
returns full provenance for all dimensions. The `/mooring/provenance`
endpoint exposes the complete provenance chain for any station.
