# ML Methodology

## Current Status

Supervised learning: **BLOCKED** — No physical measurement labels exist.
Unsupervised anomaly detection: **SCAFFOLDED** — Infrastructure ready, no training data accumulated.

## Supervised Target Status: UNAVAILABLE

No physical tension measurements, validated line angles, or surveyed
displacement records exist. Supervised tension prediction cannot be
trained without fabricating labels.

Training physics-generated tension as if it were a ground-truth target
would be circular (model-vs-model) and is explicitly prohibited.

## Unsupervised Approach (Available When Data Accumulates)

Isolation Forest on features:
- wind_speed, wind_direction
- horizontal_excursion_m
- estimated_tension_n
- forcing_mode (encoded)
- confidence (encoded)
- solver_status (encoded)

Missing current/wave values must be represented as missing — never zero-filled.

## Temporal Splitting (Mandatory)

```
TRAIN    → oldest historical period
VALIDATE → middle period
TEST     → newest period
```

No random shuffling. Station holdout also supported.
Implementation: `services/ml/splitter.py`

## Dataset Builder

`services/ml/dataset_builder.py` builds datasets from replay results.
Each row retains station_id, timestamp, model_version, configuration_version,
and all provenance metadata.

## Physics-Informed Features (Available Now)

- estimated_tension_n (MODELLED, not target)
- wind_force_n, current_force_n, wave_force_n
- horizontal_excursion_m
- forcing_mode, environmental_completeness

These can be used as features alongside raw telemetry for anomaly detection.
They cannot be used as supervised targets.

## Evaluation

When labels are unavailable: anomaly detection only.
Performance evaluation is limited — report `UNSUPERVISED_EVALUATION_LIMITED`.

Do not invent accuracy or F1 scores.
