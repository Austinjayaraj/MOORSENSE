CREATE TABLE IF NOT EXISTS mooring_configurations (
    id BIGSERIAL PRIMARY KEY,
    buoy_id TEXT NOT NULL,
    deployment_id TEXT,
    water_depth_m DOUBLE PRECISION,
    anchor_latitude DOUBLE PRECISION,
    anchor_longitude DOUBLE PRECISION,
    number_of_lines INTEGER,
    buoy_mass_kg DOUBLE PRECISION,
    buoy_buoyancy_N DOUBLE PRECISION,
    buoy_length_m DOUBLE PRECISION,
    buoy_width_m DOUBLE PRECISION,
    buoy_height_m DOUBLE PRECISION,
    projected_area_m2 DOUBLE PRECISION,
    waterplane_area_m2 DOUBLE PRECISION,
    center_of_gravity JSONB,
    center_of_buoyancy JSONB,
    pretension_N DOUBLE PRECISION,
    seabed_type TEXT,
    seabed_friction_coefficient DOUBLE PRECISION,
    source TEXT,
    source_document TEXT,
    verified BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(buoy_id, deployment_id)
);

CREATE INDEX IF NOT EXISTS mooring_config_buoy_idx ON mooring_configurations(buoy_id);

CREATE TABLE IF NOT EXISTS mooring_line_segments (
    id BIGSERIAL PRIMARY KEY,
    configuration_id BIGINT NOT NULL REFERENCES mooring_configurations(id) ON DELETE CASCADE,
    line_id TEXT NOT NULL,
    segment INTEGER NOT NULL,
    length_m DOUBLE PRECISION,
    diameter_mm DOUBLE PRECISION,
    material TEXT,
    mass_per_m DOUBLE PRECISION,
    weight_per_m DOUBLE PRECISION,
    axial_stiffness DOUBLE PRECISION,
    breaking_strength_N DOUBLE PRECISION,
    UNIQUE(configuration_id, line_id, segment)
);

CREATE INDEX IF NOT EXISTS mooring_segments_config_idx ON mooring_line_segments(configuration_id);

CREATE TABLE IF NOT EXISTS mooring_estimates (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    buoy_id TEXT NOT NULL,
    source_observation_timestamp TIMESTAMPTZ NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    environmental_forces JSONB NOT NULL,
    lines JSONB NOT NULL,
    max_tension_N DOUBLE PRECISION,
    max_utilization DOUBLE PRECISION,
    risk_level TEXT,
    model_status TEXT NOT NULL,
    raw_payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS mooring_estimates_buoy_idx ON mooring_estimates(buoy_id);
CREATE INDEX IF NOT EXISTS mooring_estimates_timestamp_idx ON mooring_estimates(source_observation_timestamp);
