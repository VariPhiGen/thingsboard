-- Convert ThingsBoard SQL-mode telemetry tables to TimescaleDB hypertable.
-- Run after pg_restore from a SQL-mode database into a Timescale-enabled database.
-- Idempotent where possible; review errors if re-run.

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Backup telemetry data from partitioned SQL schema.
DROP TABLE IF EXISTS ts_kv_mig;
CREATE TABLE ts_kv_mig AS TABLE ts_kv;

DROP TABLE IF EXISTS ts_kv_latest_mig;
CREATE TABLE ts_kv_latest_mig AS TABLE ts_kv_latest;

DROP TABLE IF EXISTS key_dictionary_mig;
CREATE TABLE key_dictionary_mig AS TABLE key_dictionary;

-- Remove SQL-mode partitioned telemetry tables and related objects.
DROP TABLE IF EXISTS ts_kv CASCADE;
DROP TABLE IF EXISTS ts_kv_latest CASCADE;
DROP TABLE IF EXISTS key_dictionary CASCADE;

-- Timescale telemetry schema (from schema-timescale.sql).
CREATE TABLE IF NOT EXISTS ts_kv (
    entity_id uuid NOT NULL,
    key int NOT NULL,
    ts bigint NOT NULL,
    bool_v boolean,
    str_v varchar(10000000),
    long_v bigint,
    dbl_v double precision,
    json_v json,
    CONSTRAINT ts_kv_pkey PRIMARY KEY (entity_id, key, ts)
);

CREATE TABLE IF NOT EXISTS key_dictionary (
    key varchar(255) NOT NULL,
    key_id serial UNIQUE,
    CONSTRAINT key_dictionary_id_pkey PRIMARY KEY (key)
);

CREATE SEQUENCE IF NOT EXISTS ts_kv_latest_version_seq cache 1;

CREATE TABLE IF NOT EXISTS ts_kv_latest (
    entity_id uuid NOT NULL,
    key int NOT NULL,
    ts bigint NOT NULL,
    bool_v boolean,
    str_v varchar(10000000),
    long_v bigint,
    dbl_v double precision,
    json_v json,
    version bigint default 0,
    CONSTRAINT ts_kv_latest_pkey PRIMARY KEY (entity_id, key)
);

SELECT create_hypertable('ts_kv', 'ts', chunk_time_interval => 604800000, if_not_exists => true);

INSERT INTO key_dictionary SELECT * FROM key_dictionary_mig
ON CONFLICT (key) DO NOTHING;

SELECT setval(
    pg_get_serial_sequence('key_dictionary', 'key_id'),
    COALESCE((SELECT MAX(key_id) FROM key_dictionary), 1)
);

INSERT INTO ts_kv (entity_id, key, ts, bool_v, str_v, long_v, dbl_v, json_v)
SELECT entity_id, key, ts, bool_v, str_v, long_v, dbl_v, json_v FROM ts_kv_mig;

INSERT INTO ts_kv_latest SELECT * FROM ts_kv_latest_mig;

DROP TABLE IF EXISTS ts_kv_mig;
DROP TABLE IF EXISTS ts_kv_latest_mig;
DROP TABLE IF EXISTS key_dictionary_mig;
