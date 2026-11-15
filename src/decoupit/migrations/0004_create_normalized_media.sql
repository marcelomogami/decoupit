CREATE TABLE normalized_media (
    id TEXT PRIMARY KEY NOT NULL,
    source_id TEXT NOT NULL UNIQUE REFERENCES source_media(id) ON DELETE CASCADE,
    absolute_path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    duration_us INTEGER NOT NULL CHECK (duration_us >= 0),
    frame_count INTEGER CHECK (frame_count IS NULL OR frame_count > 0),
    video_codec TEXT NOT NULL,
    frame_rate_num INTEGER NOT NULL,
    frame_rate_den INTEGER NOT NULL CHECK (frame_rate_den > 0),
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE UNIQUE INDEX jobs_one_active_normalization_per_source_idx
ON jobs (json_extract(payload_json, '$.source_id'))
WHERE kind = 'media.normalize_cfr30'
  AND state IN ('queued', 'running', 'cancel_requested');
