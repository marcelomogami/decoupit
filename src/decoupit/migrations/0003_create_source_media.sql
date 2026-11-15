CREATE TABLE source_media (
    id TEXT PRIMARY KEY NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    absolute_path TEXT NOT NULL,
    device INTEGER NOT NULL,
    inode INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    modified_at_ns INTEGER NOT NULL,
    format_name TEXT NOT NULL,
    duration_us INTEGER CHECK (duration_us IS NULL OR duration_us >= 0),
    video_codec TEXT NOT NULL,
    width INTEGER NOT NULL CHECK (width > 0),
    height INTEGER NOT NULL CHECK (height > 0),
    nominal_frame_rate_num INTEGER,
    nominal_frame_rate_den INTEGER,
    average_frame_rate_num INTEGER,
    average_frame_rate_den INTEGER,
    frame_rate_mode TEXT NOT NULL
        CHECK (frame_rate_mode IN ('constant', 'variable', 'unknown')),
    audio_codec TEXT,
    sample_rate INTEGER CHECK (sample_rate IS NULL OR sample_rate > 0),
    channels INTEGER CHECK (channels IS NULL OR channels > 0),
    probe_json TEXT NOT NULL,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    checked_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (project_id, absolute_path)
) STRICT;

CREATE INDEX source_media_project_idx ON source_media (project_id, created_at);
