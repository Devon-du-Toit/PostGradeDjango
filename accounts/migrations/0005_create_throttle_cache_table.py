from django.core.management import call_command
from django.db import migrations


def create_cache_tables(apps, schema_editor):
    # Login throttling stores its counts in the "throttle" database cache.
    # Running it here means every `migrate` creates the table (skipped if
    # it already exists), so no separate setup step can be forgotten.
    call_command(
        "createcachetable",
        database=schema_editor.connection.alias,
        verbosity=0,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_user_role"),
    ]

    operations = [
        migrations.RunPython(create_cache_tables, migrations.RunPython.noop),
    ]
