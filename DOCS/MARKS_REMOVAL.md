# Removing numeric grading

This release changes PostGrade to identify, verify and email uploaded scripts. Lecturers no longer enter or upload numeric grades.

## Removed

- Assessment `max_mark` and `weight` fields.
- Result model, CRUD APIs, submission marking action, gradebook and numeric assessment statistics.
- The `marked` submission status and result-version email workflow.
- Vue gradebook route, mark/result forms and score/percentage displays.

## Migration effects

1. Rename the email outbox to ScriptEmail while retaining record IDs and message/delivery history. Supersede all unsent legacy result emails; retain sent historical messages. New script records use submission/enrollment links and attachment snapshots.
2. Remove the result table and assessment maximum/weight columns. **Applying this migration deletes stored numeric results and scoring configuration. Back up the database before deployment if any historical grades must be retained externally.**
3. Convert existing `marked` scripts to `verified` if an enrollment exists, otherwise `needs_verification`. Preserve their files, enrollment and version. Normalize historical audit status labels while preserving actor, timestamp, enrollment and reasons.

No legacy script is emailed automatically. Previously sent result-text messages remain historical admin records without a submission link; they cannot be released again through the new APIs.

## Coordinated rollout

1. Back up PostgreSQL and private media using the backup/restore runbook.
2. Stop web writes and both workers. Allow active SMTP attempts to finish; do not migrate under an old worker.
3. Deploy the backend change, set `SCRIPT_EMAIL_RELEASE_POLICY` (`automatic` or `approval`), and run `python manage.py migrate`, `check`, and `makemigrations --check --dry-run`.
4. Deploy the matching Vue build. Old clients/endpoints are incompatible.
5. Start the web process and recognition/mail workers using shared private storage.
6. Smoke-test with synthetic data: create an assessment using name/date only, upload, verify, select Email script, approve when required, and inspect the one-recipient attachment in a sandbox inbox. Check that no mark input or gradebook is offered.

The result-table deletion cannot restore grades on rollback. Restore the pre-release database/media backup together with the old application versions if reverting this release. Do not rely on reversing Django migrations to recover removed values.
