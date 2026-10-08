# Uncertainty Framework

## Current Status: NOT_QUANTIFIED for all parameters

No defensible uncertainty bounds exist for any OMNI mooring parameter.

## Policy

A parameter may only enter uncertainty propagation when an explicit,
sourced distribution exists. Never use arbitrary ±10/20/30%.

When scenario bounds are deliberately assumed for research sensitivity,
label them: `SCENARIO_ASSUMPTION` — never confuse with measured uncertainty.

## Monte Carlo Engine

`services/mooring/uncertainty.py` implements:
- `UncertaintySpec` — parameter distribution with mandatory source + provenance
- `run_monte_carlo()` — reproducible (fixed seed), returns P05/P50/P95
- Returns `NOT_QUANTIFIED` if no specs provided

## What Would Enable Quantified Uncertainty

- NIOT data on MBL tolerance (e.g. manufacturing spec ± X%)
- GEBCO stated accuracy (known for some grid versions)
- Published scope variation across OMNI deployments
- Published buoy mass tolerance from manufacturer

## Current Response

All calls to `/api/buoys/{id}/mooring/uncertainty` return:
```json
{"overall_uncertainty_status": "NOT_QUANTIFIED"}
```

This is the scientifically honest answer.
