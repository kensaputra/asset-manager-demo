PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('admin', 'viewer'))
);

CREATE TABLE IF NOT EXISTS employees (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    department TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    brand         TEXT,
    serial_number TEXT,
    location      TEXT    NOT NULL,
    status        TEXT    NOT NULL CHECK (status IN ('active', 'in_storage', 'repair', 'disposed')),
    holder_id     INTEGER REFERENCES employees (id) ON DELETE SET NULL,
    purchased_on  TEXT,
    last_verified TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS handovers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id      INTEGER NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
    from_holder   INTEGER REFERENCES employees (id) ON DELETE SET NULL,
    to_holder     INTEGER REFERENCES employees (id) ON DELETE SET NULL,
    note          TEXT,
    recorded_by   TEXT    NOT NULL,
    recorded_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_assets_status   ON assets (status);
CREATE INDEX IF NOT EXISTS idx_assets_category ON assets (category);
CREATE INDEX IF NOT EXISTS idx_handovers_asset ON handovers (asset_id);
