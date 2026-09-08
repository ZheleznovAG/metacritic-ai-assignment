-- PLN-02: PostgreSQL constraint/transaction prototype, not application migrations.
-- Covers NFR-01--NFR-03, AI-01--AI-03 and the repeated-observation storage model.
-- Run with psql -X -v ON_ERROR_STOP=1. All tables are temporary; all changes roll back.
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE old_page_key (
    job_id integer, generation integer, page integer, outcome text,
    UNIQUE (job_id, generation, page)
);

CREATE TEMP TABLE probe_job (
    id integer PRIMARY KEY,
    cursor_page integer NOT NULL DEFAULT 0
);
CREATE TEMP TABLE probe_fetch (
    id integer PRIMARY KEY,
    job_id integer NOT NULL REFERENCES probe_job,
    generation integer NOT NULL,
    page integer NOT NULL,
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    outcome text NOT NULL CHECK (outcome IN
        ('started', 'succeeded', 'empty', 'failed', 'invalid', 'abandoned', 'superseded')),
    UNIQUE (job_id, generation, page, attempt_no)
);
CREATE UNIQUE INDEX one_accepted_page
    ON probe_fetch (job_id, generation, page)
    WHERE outcome IN ('succeeded', 'empty');

CREATE FUNCTION pg_temp.protect_terminal_fetch() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.outcome <> 'started' THEN
        RAISE EXCEPTION 'terminal fetch cannot be rewritten' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_terminal_fetch BEFORE UPDATE ON probe_fetch
    FOR EACH ROW EXECUTE FUNCTION pg_temp.protect_terminal_fetch();

CREATE TEMP TABLE probe_review (id integer PRIMARY KEY, text_original text NOT NULL);
CREATE TEMP TABLE probe_observation (
    fetch_id integer NOT NULL REFERENCES probe_fetch,
    review_id integer NOT NULL REFERENCES probe_review,
    PRIMARY KEY (fetch_id, review_id)
);
CREATE TEMP TABLE probe_candidate (id integer PRIMARY KEY, processed boolean NOT NULL);
CREATE TEMP TABLE probe_enrichment (
    candidate_id integer PRIMARY KEY REFERENCES probe_candidate
);

DO $$
BEGIN
    IF current_setting('server_version_num')::integer / 10000 <> 16 THEN
        RAISE EXCEPTION 'run this probe on the canonical PostgreSQL 16 major';
    END IF;

    -- The original key cannot preserve a failed fetch and its successful retry.
    INSERT INTO old_page_key VALUES (1, 1, 0, 'failed');
    BEGIN
        INSERT INTO old_page_key VALUES (1, 1, 0, 'succeeded');
        RAISE EXCEPTION 'old key unexpectedly accepted both attempts';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;

    INSERT INTO probe_job (id) VALUES (1);
    INSERT INTO probe_fetch VALUES (1, 1, 1, 0, 1, 'started');
    UPDATE probe_fetch SET outcome = 'failed' WHERE id = 1;
    INSERT INTO probe_fetch VALUES (2, 1, 1, 0, 2, 'started');

    -- A crash within page acceptance rolls back all page effects, including cursor.
    BEGIN
        INSERT INTO probe_review VALUES (1, 'Unchanged synthetic review.');
        INSERT INTO probe_observation VALUES (2, 1);
        UPDATE probe_fetch SET outcome = 'succeeded' WHERE id = 2;
        UPDATE probe_job SET cursor_page = 1 WHERE id = 1;
        RAISE EXCEPTION 'simulated crash' USING ERRCODE = 'P0002';
    EXCEPTION WHEN no_data_found THEN NULL;
    END;
    IF EXISTS (SELECT FROM probe_review) OR EXISTS (SELECT FROM probe_observation)
        OR (SELECT cursor_page FROM probe_job WHERE id = 1) <> 0
        OR (SELECT outcome FROM probe_fetch WHERE id = 2) <> 'started' THEN
        RAISE EXCEPTION 'page acceptance was not atomic';
    END IF;

    INSERT INTO probe_review VALUES (1, 'Unchanged synthetic review.');
    INSERT INTO probe_observation VALUES (2, 1);
    UPDATE probe_fetch SET outcome = 'succeeded' WHERE id = 2;
    UPDATE probe_job SET cursor_page = 1 WHERE id = 1;
    IF (SELECT count(*) FROM probe_fetch) <> 2
        OR (SELECT outcome FROM probe_fetch WHERE id = 1) <> 'failed' THEN
        RAISE EXCEPTION 'retry did not preserve the first failure';
    END IF;

    -- Both outcome types occupy the accepted-page key; a new attempt number does not bypass it.
    INSERT INTO probe_fetch VALUES (3, 1, 1, 0, 3, 'started');
    BEGIN
        UPDATE probe_fetch SET outcome = 'empty' WHERE id = 3;
        RAISE EXCEPTION 'two accepted results exist for one page';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    UPDATE probe_fetch SET outcome = 'superseded' WHERE id = 3;
    BEGIN
        INSERT INTO probe_fetch VALUES (4, 1, 1, 0, 2, 'started');
        RAISE EXCEPTION 'attempt number was reused';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        UPDATE probe_fetch SET outcome = 'started' WHERE id = 1;
        RAISE EXCEPTION 'terminal failure was rewritten';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    -- A reclaimed attempt remains abandoned when its late response arrives.
    INSERT INTO probe_fetch VALUES (4, 1, 1, 1, 1, 'started');
    UPDATE probe_fetch SET outcome = 'abandoned' WHERE id = 4;
    BEGIN
        UPDATE probe_fetch SET outcome = 'succeeded' WHERE id = 4;
        RAISE EXCEPTION 'late response reopened an abandoned attempt';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    -- A second generation reuses text but adds another observation.
    INSERT INTO probe_fetch VALUES (5, 1, 2, 0, 1, 'started');
    UPDATE probe_fetch SET outcome = 'succeeded' WHERE id = 5;
    INSERT INTO probe_observation VALUES (5, 1);
    IF (SELECT count(*) FROM probe_review) <> 1
        OR (SELECT count(*) FROM probe_observation) <> 2 THEN
        RAISE EXCEPTION 'unchanged-review storage counterexample failed';
    END IF;

    -- Core success and durable enrichment creation share the commit boundary.
    BEGIN
        INSERT INTO probe_candidate VALUES (1, true);
        INSERT INTO probe_enrichment VALUES (1);
        RAISE EXCEPTION 'simulated crash' USING ERRCODE = 'P0002';
    EXCEPTION WHEN no_data_found THEN NULL;
    END;
    IF EXISTS (SELECT FROM probe_candidate) OR EXISTS (SELECT FROM probe_enrichment) THEN
        RAISE EXCEPTION 'core/job transaction left partial effects';
    END IF;
    INSERT INTO probe_candidate VALUES (1, true);
    INSERT INTO probe_enrichment VALUES (1);
    IF (SELECT count(*) FROM probe_candidate JOIN probe_enrichment
        ON probe_candidate.id = probe_enrichment.candidate_id) <> 1 THEN
        RAISE EXCEPTION 'successful core commit did not retain enrichment intent';
    END IF;
END;
$$;

SELECT 'PASS: old-key counterexample, retry history, unique success, immutable terminal, page/core rollback, observation growth' AS result;
ROLLBACK;
