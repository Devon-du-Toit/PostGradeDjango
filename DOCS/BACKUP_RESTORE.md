# Database and media backup/restore

A usable PostGrade backup includes PostgreSQL and private media together: original scripts, recognition crops and immutable script-email attachments. A database dump alone cannot recover those bytes. Freeze web writes and both workers (or use a documented coordinated database/storage snapshot) before capturing the pair. Record the code revision, schema/migration state, UTC capture time and file manifest. Resume only after both captures complete.

## Capture

Use a restricted PostgreSQL backup role and pg_dump/pg_restore compatible with the server version. Supply credentials through a protected pgpass file or platform secret; do not print passwords or embed them in commands/logs. Keep backups private/encrypted and limit access because they contain student and authentication data.

PowerShell example (database variables and a new backup root must already be configured):

```powershell
$backupStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$dbArchive = Join-Path $backupRoot "postgrade_$backupStamp.dump"
$mediaArchive = Join-Path $backupRoot "media_$backupStamp"
if (Test-Path -LiteralPath $dbArchive) { throw 'Backup target already exists' }
if (Test-Path -LiteralPath $mediaArchive) { throw 'Media target already exists' }
& pg_dump --host=$env:DB_HOST --port=$env:DB_PORT --username=$env:DB_USER --format=custom --file=$dbArchive $env:DB_NAME
if ($LASTEXITCODE -ne 0) { throw 'Database backup failed' }
Copy-Item -LiteralPath $env:MEDIA_ROOT -Destination $mediaArchive -Recurse
& pg_restore --list $dbArchive
```

Listing the archive checks its inventory, not whether it is recoverable. Check file hashes and rehearse an actual restore. Store the dump, media tree/manifest and revision/schema metadata as one backup generation. Do not resume SMTP/recognition during capture; in-progress SMTP cannot be recalled or safely assumed undelivered.

## Restore into a new isolated target

Create a new empty database and a new media directory on a non-production target. Verify the resolved host/port/database/path before acting. Do not use --clean against a populated database and do not overwrite production as a test. Use pg_restore --exit-on-error; --no-owner is appropriate only when deliberately restoring under the target role and reviewing its grants.

```powershell
& createdb --host=$restoreHost --port=$restorePort --username=$restoreUser $restoreDatabase
if ($LASTEXITCODE -ne 0) { throw 'Target creation failed' }
& pg_restore --host=$restoreHost --port=$restorePort --username=$restoreUser --dbname=$restoreDatabase --exit-on-error --no-owner $dbArchive
if ($LASTEXITCODE -ne 0) { throw 'Restore failed' }
if (Test-Path -LiteralPath $restoreMedia) { throw 'Media target must be new' }
Copy-Item -LiteralPath $mediaArchive -Destination $restoreMedia -Recurse
```

Point Django DB_NAME/host/port and MEDIA_ROOT at the isolated restored pair. Use the matching code revision. Run check, showmigrations and the integrity audit; compare row counts, canonical row digests and SHA-256 media manifests. Test protected script/crop downloads and delivery preview/attachment bytes using a synthetic or approved test account. Keep outbound mail disabled and workers stopped. Do not replay queues blindly: restored sending/unknown deliveries can duplicate an SMTP message already accepted before the backup.

If upgrading the restored snapshot, take a new backup before migrate and execute the approved upgrade sequence. For recovery from a destructive migration, restore the database and media together with the matching pre-change code; reverse migrations cannot recreate discarded marks/results. Review signing/session secrets, restored token revocations and queued-work state before resuming users/workers. A historical dump may predate a logout/password reset, so production recovery needs an approved session-invalidation decision.

## Reproducible synthetic drill

The 2026-10-06 exercise is recorded in [DB_REVIEW.md](DB_REVIEW.md) and its evidence JSON. It used isolated postgrade_review_ scratch databases and media, verified fresh migrations, upgraded a pre-retirement fixture, dumped/restored it, and compared ten domain-table digests plus all three media hashes. It also verified restored protected file access and private email preview. No production data or outbound email was used.

For another drill, configure DEBUG=true, a new database name beginning postgrade_review_, a new MEDIA_ROOT whose final directory name begins postgrade_review_, and a synthetic SECRET_KEY. Create three empty databases: fresh, legacy and restore. Run normal migrate/check on fresh. Against the empty legacy database:

```text
python tools/database_review.py seed-legacy --output legacy-seed.json
python manage.py migrate --noinput
python tools/database_review.py measure --output measurements.json
```

Capture that database and media pair, restore into the separate empty target, then run:

```text
python manage.py check
python manage.py showmigrations
python manage.py audit_database_integrity --fail-on-invalid
python tools/database_review.py manifest --output restored-manifest.json
```

Compare measurements.json's manifest with restored-manifest.json, including migration count, table digests and every file path/hash. The tool is a guarded synthetic loader, not a production-data import command. Keep scratch targets for inspection or remove only explicitly identified scratch resources after validation; never delete a computed production path.

An approved anonymized staging rehearsal, recovery-time/recovery-point objectives, backup scheduling/retention and recurring restore drills remain [#52](https://github.com/Devon-du-Toit/PostGradeDjango/issues/52) and deployment #14. A successful synthetic restore is evidence for this procedure, not proof of production recovery capacity.
