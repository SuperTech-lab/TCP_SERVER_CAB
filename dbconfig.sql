CREATE TABLE IF NOT EXISTS channels(
    channel_id    INT PRIMARY KEY,
    name          TEXT UNIQUE NOT NULL,       
    description   TEXT
);

INSERT INTO channels (channel_id, name, description) VALUES
(1, '50K',   '50 K Stage'),
(2, '4K',    '4 K Stage'),
(5, 'STILL', 'Still Stage'),
(6, 'MXC',   'Mixing Chamber Stage');



CREATE TABLE IF NOT EXISTS runs (
    run_id      INT PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at    TIMESTAMPTZ                 
);


CREATE TABLE IF NOT EXISTS channel_data (
    run_id            INTEGER NOT NULL
                      REFERENCES runs(run_id)
                      ON DELETE CASCADE,

    channel_id        SMALLINT NOT NULL
                      REFERENCES channels(channel_id),

    ts                TIMESTAMPTZ NOT NULL,

    temperature_k     DOUBLE PRECISION,
    resistance_ohm    DOUBLE PRECISION,
    power_w           DOUBLE PRECISION,

    dwell_s           DOUBLE PRECISION,
    pause_s           DOUBLE PRECISION,
    excitation_range  TEXT,
    excitation_mode   TEXT,
    autorange         INTEGER,

    enabled           BOOLEAN,

    mxc_setpoint_mk   DOUBLE PRECISION,
    mxc_p_gain        DOUBLE PRECISION,
    mxc_i_gain        DOUBLE PRECISION,
    mxc_d_gain        DOUBLE PRECISION,
    mxc_heater_range  TEXT,

    extra             JSONB
);

CREATE INDEX IF NOT EXISTS idx_meas_run_channel_ts
    ON channel_data (run_id, channel_id, ts);

CREATE INDEX IF NOT EXISTS idx_meas_ts
    ON channel_data (ts);
