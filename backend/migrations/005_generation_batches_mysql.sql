-- Durable AI generation batches and resumable task metadata.
-- Back up the database before applying this one-time migration.

ALTER TABLE generate_tasks
    ADD COLUMN failed_chunks INT NOT NULL DEFAULT 0 COMMENT 'Failed generation batches',
    ADD COLUMN num_direct INT NOT NULL DEFAULT 3 COMMENT 'Direct questions requested per batch',
    ADD COLUMN num_logic INT NOT NULL DEFAULT 2 COMMENT 'Logic questions requested per batch',
    ADD COLUMN partial_success TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Whether only part of the document succeeded';

CREATE TABLE generation_batches (
    id INT NOT NULL AUTO_INCREMENT,
    task_id VARCHAR(64) NOT NULL,
    bank_id INT NOT NULL,
    batch_index INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    source_text TEXT NULL,
    generated_count INT NOT NULL DEFAULT 0,
    attempt_count INT NOT NULL DEFAULT 0,
    error TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    started_at DATETIME NULL,
    completed_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_generation_batches_task_index (task_id, batch_index),
    KEY ix_generation_batches_task_id (task_id),
    KEY ix_generation_batches_bank_id (bank_id),
    KEY ix_generation_batches_status (status),
    CONSTRAINT fk_generation_batches_task
        FOREIGN KEY (task_id) REFERENCES generate_tasks (id),
    CONSTRAINT fk_generation_batches_bank
        FOREIGN KEY (bank_id) REFERENCES question_banks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
