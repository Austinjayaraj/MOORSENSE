# OMNI Mooring Configuration Evidence

## Overview

This document records every piece of evidence found for OMNI mooring parameters,
classified by source type and authoritative status. Parameters not established from
authoritative sources remain UNKNOWN or ASSUMPTION.

---

## Evidence Sources Reviewed

| Source | Type | URL | Date |
|--------|------|-----|------|
| INCOIS OMNI page | Institutional | https://www.incois.gov.in/site/datainfo/jointportal.jsp | 2026-10-08 |
| OSICON-23 abstract volume | Conference proceedings | https://osicon23.incois.gov.in/documents/AbstractVolumeOSICON-23.pdf | 2026-10-08 |
| INCOIS data holdings | Institutional | https://incois.gov.in/site/dataholdings.jsp | 2026-10-08 |
| MoES OMNI overview | Government | https://www.incois.gov.in | 2026-10-08 |

---

## Parameters — Evidence Table

| Parameter | Value | Station | Source | Source Type | Exact Context | Confidence | Auth Status | Allowed for Physics | Notes |
|-----------|-------|---------|--------|-------------|---------------|------------|-------------|---------------------|-------|
| Mooring type | Inverse-catenary / slack mooring | All OMNI | OSICON-23 | PUBLISHED_REFERENCE | "single-point inverse-catenary mooring" | MEDIUM | PUBLISHED_REFERENCE | YES — as architecture class | Design class, not per-station verified |
| Scope | ≈ 1.22 | Mentioned in context of BD11 | OSICON-23 | PUBLISHED_REFERENCE | "mooring scope 1.22" adjacent to BD11 ~3250m discussion | MEDIUM | PUBLISHED_REFERENCE | YES — as reference assumption | Interpretation: L ≈ 1.22 × D. Not confirmed as universal across all stations. |
| Deployment depth (BD11) | ~3250 m | BD11 | OSICON-23 | PUBLISHED_REFERENCE | "BD11 at approximately 3250 m" | MEDIUM | PUBLISHED_REFERENCE | YES — as reference depth | Approximate, not surveyed deployment depth |
| Mooring count (lines) | 1 | All OMNI | INCOIS OMNI page | INSTITUTIONAL | "single-point mooring" | HIGH | PUBLISHED_REFERENCE | YES | Consistent with all literature |
| Buoy dimensions | UNKNOWN | All | No source found | — | — | — | UNKNOWN | Use reference only | No peer-reviewed or deployment spec found |
| Buoy mass | UNKNOWN | All | No source found | — | — | — | UNKNOWN | Use reference only | |
| Buoy net buoyancy | UNKNOWN | All | No source found | — | — | — | UNKNOWN | Use reference only | |
| Rope diameter | UNKNOWN | All | No source found | — | — | UNKNOWN | UNKNOWN | Do not use for MBL calculation | Not established from any source |
| Rope MBL | UNKNOWN | All | No source found | — | — | UNKNOWN | UNKNOWN | ASSUMPTION only | 250 kN is generic, unverified |
| Chain diameter | UNKNOWN | All | No source found | — | — | UNKNOWN | UNKNOWN | ASSUMPTION only | |
| Chain MBL | UNKNOWN | All | No source found | — | — | UNKNOWN | UNKNOWN | ASSUMPTION only | 490 kN is generic, unverified |
| Segment proportions | UNKNOWN | All | No source found | — | — | UNKNOWN | UNKNOWN | ASSUMPTION only | 5/85/10% is entirely assumed |
| Pretension | UNKNOWN | All | No source found | — | — | UNKNOWN | UNKNOWN | ASSUMPTION only | 10% net buoyancy is engineering assumption |
| Anchor coordinates | UNKNOWN | All | No source found | — | — | UNKNOWN | UNKNOWN | Cannot use for catenary | Registry position ≠ anchor position |
| Fairlead depth | UNKNOWN | All | No source found | — | — | UNKNOWN | UNKNOWN | ASSUMPTION only | 1.5 m assumed |
| Seabed type | UNKNOWN | All | No source found | — | — | UNKNOWN | UNKNOWN | Not in model | |
| Water depth (all stations) | See table | Per station | GEBCO_2026 WMS | EXTERNAL_DATASET | GEBCO_LATEST_2 layer | MEDIUM | INFERRED | YES — as bathymetry input | Not deployment survey depth |

---

## Station Depths from GEBCO_2026 (retrieved 2026-10-08)

| Station | Lat | Lon | GEBCO Depth (m) | Derived L (m, scope=1.22) | Status |
|---------|-----|-----|-----------------|--------------------------|--------|
| AD06 | 18.495 | 67.450 | 3338 | 4072 | INFERRED |
| AD07 | 14.931 | 68.976 | 3977 | 4852 | INFERRED |
| AD08 | 12.068 | 68.633 | 4301 | 5247 | INFERRED |
| AD09 | 8.183 | 73.298 | 2090 | 2550 | INFERRED |
| AD10 | 10.322 | 72.587 | 1617 | 1973 | INFERRED |
| BD08 | 17.825 | 89.236 | 2140 | 2611 | INFERRED |
| BD09 | 17.500 | 89.117 | 2298 | 2804 | INFERRED |
| BD10 | 16.362 | 87.990 | 2627 | 3205 | INFERRED |
| BD11 | 13.525 | 84.167 | 3229 | 3939 | INFERRED |
| BD12 | 10.515 | 94.074 | 2973 | 3627 | INFERRED |
| BD13 | 13.990 | 86.997 | 3014 | 3677 | INFERRED |
| BD14 | 6.571 | 88.233 | 3832 | 4675 | INFERRED |

---

## Scope Semantics (Phase 4A)

**Question**: Does "scope 1.22" mean `L_total = 1.22 × D`?

**Evidence**: OSICON-23 discusses mooring scope in the context of OMNI design.
Standard mooring engineering defines scope as the ratio of total mooring line
length to water depth: `scope = L / D`.

**Interpretation used**: `L ≈ scope × D = 1.22 × D`

**Caveats**:
- This interpretation is consistent with standard catenary mooring scope definition
- Fairlead depth and line geometry mean the actual deployed-line-to-depth ratio may differ
- The figure 1.22 appears in a conference abstract, not a deployment specification
- Scope may vary between stations
- This remains PUBLISHED_REFERENCE, not DEPLOYMENT_VERIFIED

**Decision**: Retain `L = 1.22 × D` as screening assumption with provenance = PUBLISHED_REFERENCE.

---

## Parameters Requiring Authoritative NIOT Documentation

The following are required for engineering-grade mooring analysis but remain UNKNOWN:

- Actual deployed line diameter (all stations)
- Actual minimum breaking load / MBL (all stations)
- Actual segment lengths and materials
- Actual pretension at deployment
- Actual anchor coordinates (not registry buoy position)
- Actual deployment depth from survey
- Actual buoy dimensions and mass
- Recovery/inspection tension records
- Station-specific scope verification

**Source needed**: NIOT Ocean Observing System deployment reports or technical manuals.

---

## Classification Summary

| Class | Parameters |
|-------|-----------|
| PUBLISHED_REFERENCE | Mooring type (inverse catenary), Single-point, Scope ≈ 1.22, BD11 ~3250m |
| INFERRED | Water depth for all 12 stations (GEBCO_2026) |
| DERIVED | Line length = scope × GEBCO depth |
| ASSUMPTION | Rope/chain MBL, diameters, weights, segment proportions, pretension, fairlead depth, buoy geometry |
| UNKNOWN | All station-specific deployment dimensions, anchor coordinates, actual pretension |
