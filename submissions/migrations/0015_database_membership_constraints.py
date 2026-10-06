"""PostgreSQL keys enforced even when ORM validation is bypassed.

The redundant keys belong to the database, not writable Django fields.
Composite foreign keys use PostgreSQL's referential-integrity row locking.
"""

from django.db import migrations

FORWARD = """
LOCK TABLE courses_course, students_student, assessments_assessment,
    students_enrollment, submissions_submission IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM students_enrollment e
        JOIN courses_course c ON c.id = e.course_id
        JOIN students_student s ON s.id = e.student_id
        WHERE c.owner_id <> s.owner_id
    ) OR EXISTS (
        SELECT 1 FROM submissions_submission s
        JOIN assessments_assessment a ON a.id = s.assessment_id
        JOIN students_enrollment e ON e.id = s.enrollment_id
        WHERE a.course_id <> e.course_id
    ) THEN
        RAISE EXCEPTION 'Invalid membership data: run audit_database_integrity --fail-on-invalid and approve explicit repair before migrating';
    END IF;
END $$;

ALTER TABLE courses_course ADD CONSTRAINT pg51_course_owner_key UNIQUE (id, owner_id);
ALTER TABLE students_student ADD CONSTRAINT pg51_student_owner_key UNIQUE (id, owner_id);
ALTER TABLE assessments_assessment ADD CONSTRAINT pg51_assessment_course_key UNIQUE (id, course_id);
ALTER TABLE students_enrollment ADD CONSTRAINT pg51_enrollment_course_key UNIQUE (id, course_id);
ALTER TABLE students_enrollment ADD CONSTRAINT pg51_enrollment_student_key UNIQUE (id, student_id);
ALTER TABLE students_enrollment ADD COLUMN db_owner_key bigint;
ALTER TABLE submissions_submission ADD COLUMN db_course_key bigint;
ALTER TABLE submissions_submission ADD COLUMN db_student_key bigint;
UPDATE students_enrollment e SET db_owner_key = c.owner_id FROM courses_course c WHERE c.id = e.course_id;
UPDATE submissions_submission s SET db_course_key = a.course_id FROM assessments_assessment a WHERE a.id = s.assessment_id;
UPDATE submissions_submission s SET db_student_key = e.student_id FROM students_enrollment e WHERE e.id = s.enrollment_id;
-- Backfills can queue Django's deferred FK trigger events when a row is
-- updated twice. Flush them before subsequent ALTER TABLE statements.
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE students_enrollment ALTER COLUMN db_owner_key SET NOT NULL;
ALTER TABLE submissions_submission ALTER COLUMN db_course_key SET NOT NULL;
ALTER TABLE submissions_submission ADD CONSTRAINT pg51_submission_identity_shape
    CHECK ((enrollment_id IS NULL) = (db_student_key IS NULL));

CREATE FUNCTION pg51_enrollment_keys() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.db_owner_key := (SELECT owner_id FROM courses_course WHERE id = NEW.course_id);
    RETURN NEW;
END $$;
CREATE TRIGGER pg51_enrollment_keys BEFORE INSERT OR UPDATE ON students_enrollment
    FOR EACH ROW EXECUTE FUNCTION pg51_enrollment_keys();
CREATE FUNCTION pg51_submission_keys() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.db_course_key := (SELECT course_id FROM assessments_assessment WHERE id = NEW.assessment_id);
    NEW.db_student_key := (SELECT student_id FROM students_enrollment WHERE id = NEW.enrollment_id);
    RETURN NEW;
END $$;
CREATE TRIGGER pg51_submission_keys BEFORE INSERT OR UPDATE ON submissions_submission
    FOR EACH ROW EXECUTE FUNCTION pg51_submission_keys();

ALTER TABLE students_enrollment ADD CONSTRAINT pg51_enrollment_course_owner
    FOREIGN KEY (course_id, db_owner_key) REFERENCES courses_course (id, owner_id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE students_enrollment ADD CONSTRAINT pg51_enrollment_student_owner
    FOREIGN KEY (student_id, db_owner_key) REFERENCES students_student (id, owner_id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE submissions_submission ADD CONSTRAINT pg51_submission_assessment_course
    FOREIGN KEY (assessment_id, db_course_key) REFERENCES assessments_assessment (id, course_id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE submissions_submission ADD CONSTRAINT pg51_submission_enrollment_course
    FOREIGN KEY (enrollment_id, db_course_key) REFERENCES students_enrollment (id, course_id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE submissions_submission ADD CONSTRAINT pg51_submission_enrollment_student
    FOREIGN KEY (enrollment_id, db_student_key) REFERENCES students_enrollment (id, student_id)
    DEFERRABLE INITIALLY IMMEDIATE;
"""

REVERSE = """
ALTER TABLE submissions_submission DROP CONSTRAINT pg51_submission_enrollment_student;
ALTER TABLE submissions_submission DROP CONSTRAINT pg51_submission_enrollment_course;
ALTER TABLE submissions_submission DROP CONSTRAINT pg51_submission_assessment_course;
ALTER TABLE students_enrollment DROP CONSTRAINT pg51_enrollment_student_owner;
ALTER TABLE students_enrollment DROP CONSTRAINT pg51_enrollment_course_owner;
DROP TRIGGER pg51_submission_keys ON submissions_submission;
DROP TRIGGER pg51_enrollment_keys ON students_enrollment;
DROP FUNCTION pg51_submission_keys();
DROP FUNCTION pg51_enrollment_keys();
ALTER TABLE submissions_submission DROP COLUMN db_course_key;
ALTER TABLE submissions_submission DROP COLUMN db_student_key;
ALTER TABLE students_enrollment DROP COLUMN db_owner_key;
ALTER TABLE students_enrollment DROP CONSTRAINT pg51_enrollment_course_key;
ALTER TABLE students_enrollment DROP CONSTRAINT pg51_enrollment_student_key;
ALTER TABLE assessments_assessment DROP CONSTRAINT pg51_assessment_course_key;
ALTER TABLE students_student DROP CONSTRAINT pg51_student_owner_key;
ALTER TABLE courses_course DROP CONSTRAINT pg51_course_owner_key;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("submissions", "0014_submissionaudit_new_identity_and_more"),
        ("students", "0003_enrollment"),
        ("courses", "0003_course_archived_at"),
        ("assessments", "0004_assessment_archived_at"),
    ]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
