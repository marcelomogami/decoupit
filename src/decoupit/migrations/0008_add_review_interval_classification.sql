ALTER TABLE review_intervals
ADD COLUMN classification TEXT
    CHECK (
        classification IS NULL
        OR classification IN ('primary', 'alternative', 'blooper', 'discard')
    );
