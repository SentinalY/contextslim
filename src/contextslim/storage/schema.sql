-- ContextSlim storage schema.
--
-- Deliberately narrow and portable: no SQLite-only column types, no triggers,
-- no JSON1 functions. Moving to PostgreSQL later is a driver swap behind
-- CapsuleStore, not a rewrite (see the risk register in the product doc).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capsules (
    session_id        TEXT PRIMARY KEY,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    mode              TEXT    NOT NULL CHECK (mode IN ('slim', 'deep')),
    version           INTEGER NOT NULL DEFAULT 1,
    title             TEXT,
    project           TEXT,
    capsule_json      TEXT    NOT NULL,
    capsule_text      TEXT    NOT NULL,
    raw_tokens        INTEGER NOT NULL DEFAULT 0,
    compressed_tokens INTEGER NOT NULL DEFAULT 0,
    reduction_pct     REAL    NOT NULL DEFAULT 0,
    source_files      TEXT    NOT NULL DEFAULT '[]',
    model             TEXT,
    fallback_reason   TEXT,
    restore_count     INTEGER NOT NULL DEFAULT 0,
    last_restored_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_capsules_created_at ON capsules (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_capsules_project    ON capsules (project);

-- Every update_capsule() call archives the previous state here, so a capsule
-- is a living, versioned project memory rather than a destructive overwrite.
CREATE TABLE IF NOT EXISTS capsule_versions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT    NOT NULL REFERENCES capsules (session_id) ON DELETE CASCADE,
    version           INTEGER NOT NULL,
    created_at        TEXT    NOT NULL,
    mode              TEXT    NOT NULL,
    capsule_json      TEXT    NOT NULL,
    capsule_text      TEXT    NOT NULL,
    raw_tokens        INTEGER NOT NULL DEFAULT 0,
    compressed_tokens INTEGER NOT NULL DEFAULT 0,
    note              TEXT,
    UNIQUE (session_id, version)
);

CREATE INDEX IF NOT EXISTS idx_versions_session ON capsule_versions (session_id, version DESC);
