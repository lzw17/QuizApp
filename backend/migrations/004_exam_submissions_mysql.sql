-- Persist final exam results so retrying POST /api/exam/submit is idempotent.
CREATE TABLE IF NOT EXISTS exam_submissions (
    session_id VARCHAR(64) NOT NULL,
    user_id INT NOT NULL,
    bank_id INT NOT NULL,
    result JSON NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id),
    KEY ix_exam_submissions_user_id (user_id),
    KEY ix_exam_submissions_bank_id (bank_id),
    CONSTRAINT fk_exam_submissions_session
        FOREIGN KEY (session_id) REFERENCES exam_sessions (id),
    CONSTRAINT fk_exam_submissions_user
        FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_exam_submissions_bank
        FOREIGN KEY (bank_id) REFERENCES question_banks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
