# Backup and Restore

## What this covers

How to back up and restore the PostGrade PostgreSQL database. Same steps work for local, staging, or production.

The live demo of the restore process is waiting on a non production database to test against.

## What you need

pg_dump and pg_restore on the machine running the backup. They ship with PostgreSQL 17.

Credentials for the source database.

A target database for restore, with a user who can create tables.

Values below come from .env:

DB_NAME, default postgrade
DB_USER, default postgrade_user
DB_HOST, default localhost
DB_PORT, default 5432 locally, 5433 in some setups

## Backup

### Plain SQL

Readable file. Good for small databases and when you want to inspect what is inside.

pg_dump --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --format=plain --file="backup_$(date +%Y%m%d_%H%M%S).sql" "$DB_NAME"

### Custom format

Smaller, faster, and you can restore pieces of it. This is what I would use for anything real.

pg_dump --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --format=custom --file="backup_$(date +%Y%m%d_%H%M%S).dump" "$DB_NAME"

### Checking the backup file

pg_restore --list backup_YYYYMMDD_HHMMSS.dump | head

If it prints a list of objects, the file is fine.

## Restore

### Plain SQL

psql --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="$DB_NAME" --file="backup_YYYYMMDD_HHMMSS.sql"

### Custom format

If the target database is empty:

pg_restore --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="$DB_NAME" --clean --if-exists "backup_YYYYMMDD_HHMMSS.dump"

The clean and if exists flags drop what is already there before recreating it. Only run this against a database you are allowed to overwrite.

## How to demonstrate recovery

1. Take a backup of the source database with the custom format.
2. Create a fresh target database, for example postgrade_restore_test.
3. Restore the backup into the target with pg_restore.
4. Point Django at the target and run its checks:

DB_NAME=postgrade_restore_test python manage.py check
DB_NAME=postgrade_restore_test python manage.py showmigrations

5. Compare row counts on a couple of tables:

psql -d postgrade_restore_test -c "SELECT COUNT(*) FROM submissions_submission;"
psql -d postgrade_restore_test -c "SELECT COUNT(*) FROM students_student;"

6. Drop the target database.

## Status

The procedure is documented above. The live demo of steps 1 to 6 is waiting on a non production database that can be overwritten and dropped.
