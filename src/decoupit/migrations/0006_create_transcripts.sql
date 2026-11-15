CREATE TABLE transcription_runs (
    id TEXT PRIMARY KEY NOT NULL,
    normalized_media_id TEXT NOT NULL
        REFERENCES normalized_media(id) ON DELETE CASCADE,
    profile_hash TEXT NOT NULL CHECK (length(profile_hash) = 64),
    profile_json TEXT NOT NULL,
    raw_output_path TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL,
    language_probability REAL NOT NULL
        CHECK (language_probability >= 0 AND language_probability <= 1),
    duration_us INTEGER NOT NULL CHECK (duration_us >= 0),
    duration_after_vad_us INTEGER NOT NULL CHECK (duration_after_vad_us >= 0),
    segment_count INTEGER NOT NULL CHECK (segment_count >= 0),
    word_count INTEGER NOT NULL CHECK (word_count >= 0),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (normalized_media_id, profile_hash)
) STRICT;

CREATE TABLE transcript_segments (
    transcription_run_id TEXT NOT NULL
        REFERENCES transcription_runs(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL CHECK (segment_index >= 0),
    start_us INTEGER NOT NULL CHECK (start_us >= 0),
    end_us INTEGER NOT NULL CHECK (end_us >= start_us),
    text TEXT NOT NULL,
    PRIMARY KEY (transcription_run_id, segment_index)
) STRICT, WITHOUT ROWID;

CREATE TABLE transcript_words (
    transcription_run_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    word_index INTEGER NOT NULL CHECK (word_index >= 0),
    start_us INTEGER NOT NULL CHECK (start_us >= 0),
    end_us INTEGER NOT NULL CHECK (end_us >= start_us),
    text TEXT NOT NULL,
    probability REAL NOT NULL CHECK (probability >= 0 AND probability <= 1),
    PRIMARY KEY (transcription_run_id, segment_index, word_index),
    FOREIGN KEY (transcription_run_id, segment_index)
        REFERENCES transcript_segments(transcription_run_id, segment_index)
        ON DELETE CASCADE
) STRICT, WITHOUT ROWID;

CREATE INDEX transcription_runs_media_idx
ON transcription_runs (normalized_media_id, created_at);

CREATE UNIQUE INDEX jobs_one_active_transcription_per_source_idx
ON jobs (json_extract(payload_json, '$.source_id'))
WHERE kind = 'media.transcribe_words'
  AND state IN ('queued', 'running', 'cancel_requested');
