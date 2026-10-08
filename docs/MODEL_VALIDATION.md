# Model Validation Status

## Current Status: NOT_VALIDATED

No physical validation has been performed. No physical measurements exist against
which to compare model outputs.

## Available Validation Types (All Currently Null)

| Type | Status | Notes |
|------|--------|-------|
| Physical tension | NOT_VALIDATED | No tension sensor data available |
| Measured line angle | NOT_VALIDATED | No inclinometer data available |
| Measured displacement | NOT_IMPLEMENTED | GPS trajectory model comparison not implemented |
| Recovery/inspection records | NOT_VALIDATED | No records obtained from NIOT |
| Storm response | NOT_VALIDATED | No reference storm data identified |

## Validation Framework

`services/mooring/validation.py` provides:
- `compare_model_measurement(modelled, measured)` — when physical data exists
- `MeasuredTension`, `MeasuredLineAngle`, `MeasuredDisplacement` models
- `ValidationMetrics` with MAE, RMSE, bias, relative error

## What Would Constitute Valid Evidence

1. Physical tension/load cell recordings from a deployed OMNI buoy
2. GPS position time series showing actual buoy excursion
3. Line angle measurements from inclinometers
4. Recovery inspection data (measured pretension, line condition)
5. Deployment specification sheets from NIOT/OOS

## Why Model-vs-Model Is Not Physical Validation

Comparing one physics model against another or against physics-generated data
is NOT physical validation. It may reveal numerical consistency but cannot
confirm that the model accurately represents reality.

## Disclaimer

All mooring model outputs are SCREENING-LEVEL ESTIMATES until validated
against physical measurements.
