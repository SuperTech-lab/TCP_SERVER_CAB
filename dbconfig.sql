/* CREATE TABLE IF NOT EXISTS channels(
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
    ON channel_data (ts); GRANT ALL PRIVILEGES
ON TABLE public.relation_runs, public.relation_data
TO lakeshore_app;    SELECT
  file_name,
  convert_from(data, 'UTF8') AS dat_content
FROM public.relation_files
WHERE file_name = '2026_01_21_182828_RvsT_Defi.dat';   */

CREATE TABLE IF NOT EXISTS public.relation_files (
  file_name   text PRIMARY KEY,          -- ej: 0121_RvRvsT_miprueba.dat
  created_at  timestamptz NOT NULL DEFAULT now(),
  channel_number int NOT NULL,
  label       text,
  n_points    int NOT NULL,
  content_type text NOT NULL DEFAULT 'text/plain',
  data        bytea NOT NULL              -- el .dat entero
);

CREATE INDEX IF NOT EXISTS idx_relation_files_created
  ON public.relation_files (created_at DESC);

GRANT ALL PRIVILEGES ON TABLE public.relation_files TO lakeshore_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO lakeshore_app;  -- por si otras tablas usan secuencias

