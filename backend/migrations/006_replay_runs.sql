-- Replay run registry. Each row tracks one POST /mooring/replay invocation.
-- Results in mooring_replay_results reference run_id.

CREATE TABLE IF NOT EXISTS mooring_replay_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL UNIQUE,
    station_id      TEXT NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'QUEUED',
    observation_count   INTEGER,
    success_count       INTEGER,
    failure_count       INTEGER,
    model_version       TEXT,
    physics_version     TEXT,
    configuration_version TEXT,
    input_hash      TEXT,
    error_summary   TEXT
);

CREATE INDEX IF NOT EXISTS replay_runs_station_idx ON mooring_replay_runs(station_id);
CREATE INDEX IF NOT EXISTS replay_runs_run_id_idx  ON mooring_replay_runs(run_id);

-- Add run_id column to replay results to link them
ALTER TABLE mooring_replay_results ADD COLUMN IF NOT EXISTS run_id TEXT;
CREATE INDEX IF NOT EXISTS replay_results_run_id_idx ON mooring_replay_results(run_id);
