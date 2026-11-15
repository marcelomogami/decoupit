CREATE TABLE waveforms (
    id TEXT PRIMARY KEY NOT NULL,
    normalized_media_id TEXT NOT NULL UNIQUE
        REFERENCES normalized_media(id) ON DELETE CASCADE,
    absolute_path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    point_count INTEGER NOT NULL CHECK (point_count > 0),
    sample_rate INTEGER NOT NULL CHECK (sample_rate > 0),
    samples_per_point INTEGER NOT NULL CHECK (samples_per_point > 0),
    format_version INTEGER NOT NULL CHECK (format_version > 0),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE UNIQUE INDEX jobs_one_active_waveform_per_source_idx
ON jobs (json_extract(payload_json, '$.source_id'))
WHERE kind = 'media.generate_waveform'
  AND state IN ('queued', 'running', 'cancel_requested');
