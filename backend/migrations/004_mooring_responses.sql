-- Mooring Digital Twin response and trajectory tables.
-- mooring_responses stores every physics model run for reproducibility.
-- mooring_trajectory stores buoy position history for anchor estimation.

CREATE TABLE IF NOT EXISTS mooring_responses (
    id BIGSERIAL PRIMARY KEY,
    buoy_id TEXT NOT NULL,
    observation_timestamp TIMESTAMPTZ NOT NULL,
    model_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    fairlead_tension_n DOUBLE PRECISION,
    anchor_tension_n DOUBLE PRECISION,
    horizontal_tension_n DOUBLE PRECISION,
    vertical_tension_n DOUBLE PRECISION,
    line_angle_deg DOUBLE PRECISION,
    horizontal_excursion_m DOUBLE PRECISION,
    watch_circle_radius_m DOUBLE PRECISION,
    watch_circle_utilization DOUBLE PRECISION,
    utilization DOUBLE PRECISION,
    safety_factor DOUBLE PRECISION,
    wind_force_n DOUBLE PRECISION,
    current_force_n DOUBLE PRECISION,
    wave_force_n DOUBLE PRECISION,
    total_environmental_force_n DOUBLE PRECISION,
    risk_state TEXT,
    confidence TEXT,
    solver_converged BOOLEAN,
    solver_iterations INTEGER,
    solver_residual DOUBLE PRECISION,
    configuration_status TEXT,
    configuration_version TEXT,
    model_version TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(buoy_id, observation_timestamp, model_version)
);

CREATE INDEX IF NOT EXISTS mooring_responses_buoy_idx ON mooring_responses(buoy_id);
CREATE INDEX IF NOT EXISTS mooring_responses_ts_idx ON mooring_responses(observation_timestamp);
CREATE INDEX IF NOT EXISTS mooring_responses_buoy_ts_idx ON mooring_responses(buoy_id, observation_timestamp DESC);

CREATE TABLE IF NOT EXISTS mooring_trajectory (
    id BIGSERIAL PRIMARY KEY,
    buoy_id TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    distance_from_anchor_m DOUBLE PRECISION,
    bearing_from_anchor_deg DOUBLE PRECISION,
    source TEXT DEFAULT 'INCOIS_REGISTRY'
);

CREATE INDEX IF NOT EXISTS mooring_trajectory_buoy_idx ON mooring_trajectory(buoy_id);
CREATE INDEX IF NOT EXISTS mooring_trajectory_ts_idx ON mooring_trajectory(buoy_id, timestamp DESC);
