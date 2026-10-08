# Engineering Limitations

## What MoorSense Is

A research-grade screening-level digital twin for NIOT/OOS OMNI mooring buoys.
It combines real INCOIS telemetry with GEBCO bathymetry and OMNI reference
mooring architecture to produce screening-level estimated mooring responses.

## What MoorSense Is NOT

- A certified engineering analysis tool
- A replacement for authoritative NIOT deployment documentation
- A replacement for dynamic mooring analysis (FEA, time-domain simulation)
- A source of actual mooring tension measurements
- A validated structural integrity assessment

## Explicit Limitations

### Configuration
- No authoritative station-specific mooring configuration has been obtained
- Line diameters, MBL, segment lengths are ASSUMPTION values
- Pretension is an engineering assumption (10% net buoyancy), not deployment setting
- Segment proportions (5/85/10%) are entirely assumed
- Scope 1.22 is from published OMNI design — not verified per station
- Anchor coordinates are unknown — registry position ≠ anchor

### Environmental Forcing
- Wave parameters are NOT_OFFERED or NO_DATA for most stations
- Current measurements are NOT_OFFERED for most stations
- Wind-only forcing significantly underestimates total environmental load
- Estimated tension in wind-only mode is a LOWER BOUND, not the total load

### Physics Model
- Quasi-static analysis only — no dynamic amplification
- Simplified Morison wave forcing — not full hydrodynamic RAO analysis
- No vortex-induced vibration (VIV) modeling
- No fatigue accumulation model
- No marine growth or corrosion effects
- Equal load on single mooring line (single-point architecture)
- Line self-weight dominates tension at depth — geometric effect, not dynamic load

### Bathymetry
- GEBCO_2026 is inferred bathymetry (~500m resolution)
- Actual deployment depth may differ significantly
- GEBCO should not be used for navigation or safety-at-sea purposes

### Validation
- No physical tension measurements are available
- Model has not been validated against deployment observations
- Utilization and safety factors are based on assumed MBL — NOT engineering-certified
- All outputs are screening-level estimates

## Risk of False Confidence

The system produces numerical tension values even with poor configuration.
Users must read the confidence level and provenance before interpreting results.
A LOW confidence result with ASSUMPTION configuration should NOT be used for
engineering decisions.

## Required Authoritative Data

To upgrade from screening-level to engineering-grade analysis:
1. NIOT/OOS deployment specifications per station (line dimensions, MBL, pretension)
2. Bathymetric survey at deployment site
3. Anchor position (not registry buoy position)
4. Physical tension measurement or validation dataset
5. Recovery/inspection reports
