-- Mooring historical replay results.
-- Append-only: results from different model versions coexist.
-- Deterministic key: (station_id, observation_timestamp, model_version, physics_version)
-- prevents duplicate storage of identical computations.

CREATE TABLE IF NOT EXISTS mooring_replay_results (
    id                      BIGSERIAL PRIMARY KEY,
    station_id              TEXT NOT NULL,
    observation_timestamp   TIMESTAMPTZ NOT NULL,
    configuration_version   TEXT,
    model_version           TEXT,
    physics_version         TEXT,
    environment_version     TEXT,

    -- Environmental inputs (null = unavailable, never 0-substituted)
    wind_speed              DOUBLE PRECISION,
    wind_direction          DOUBLE PRECISION,
    current_speed           DOUBLE PRECISION,
    current_direction       DOUBLE PRECISION,
    wave_height             DOUBLE PRECISION,
    wave_period             DOUBLE PRECISION,
    wave_direction          DOUBLE PRECISION,

    -- Computed forces (null = not computed / input unavailable)
    wind_force_n            DOUBLE PRECISION,
    current_force_n         DOUBLE PRECISION,
    wave_force_n            DOUBLE PRECISION,
    total_known_force_n     DOUBLE PRECISION,

    -- Physics outputs
    estimated_tension_n     DOUBLE PRECISION,
    estimated_line_angle_deg DOUBLE PRECISION,
    estimated_anchor_load_n  DOUBLE PRECISION,
    horizontal_excursion_m  DOUBLE PRECISION,

    -- Risk and quality
    data_risk               TEXT,
    model_risk              TEXT,
    mooring_risk            TEXT,
    overall_risk_status     TEXT,
    confidence              TEXT,
    environmental_completeness TEXT,
    forcing_mode            TEXT,
    solver_status           TEXT,

    -- Metadata
    replay_created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    provenance_json         JSONB,
    raw_result_json         JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Prevent duplicate identical computations
    UNIQUE (station_id, observation_timestamp, model_version, physics_version)
);

CREATE INDEX IF NOT EXISTS moor_replay_station_idx ON mooring_replay_results(station_id);
CREATE INDEX IF NOT EXISTS moor_replay_ts_idx      ON mooring_replay_results(observation_timestamp);
CREATE INDEX IF NOT EXISTS moor_replay_st_ts_idx   ON mooring_replay_results(station_id, observation_timestamp DESC);
