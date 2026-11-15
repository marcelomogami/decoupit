CREATE TABLE jobs (
    id TEXT PRIMARY KEY NOT NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (length(trim(kind)) > 0),
    state TEXT NOT NULL CHECK (
        state IN (
            'queued',
            'running',
            'cancel_requested',
            'succeeded',
            'failed',
            'cancelled'
        )
    ),
    payload_json TEXT NOT NULL DEFAULT '{}',
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    process_id INTEGER CHECK (process_id IS NULL OR process_id > 0),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at TEXT,
    finished_at TEXT,
    cancellation_requested_at TEXT,
    error_message TEXT
) STRICT;

CREATE INDEX jobs_runnable_idx ON jobs (state, created_at)
    WHERE state = 'queued';
