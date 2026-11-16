CREATE TABLE review_intervals (
    id TEXT PRIMARY KEY NOT NULL,
    normalized_media_id TEXT NOT NULL
        REFERENCES normalized_media(id) ON DELETE CASCADE,
    start_frame INTEGER NOT NULL CHECK (start_frame >= 0),
    end_frame INTEGER NOT NULL CHECK (end_frame >= start_frame),
    created_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX review_intervals_media_frames_idx
ON review_intervals (normalized_media_id, start_frame, end_frame);
