from django.db import migrations


class Migration(migrations.Migration):
    """
    Idempotent: uses IF NOT EXISTS throughout so it is safe whether the
    production DB already has these columns/indexes (old migration chain)
    or is a fresh install where 0002 already created everything.
    """

    dependencies = [
        ('activities', '0018_add_missing_db_fields'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE activities_activity
                            ADD COLUMN IF NOT EXISTS tendering_date date NULL,
                            ADD COLUMN IF NOT EXISTS order_date      date NULL,
                            ADD COLUMN IF NOT EXISTS delivery_date   date NULL,
                            ADD COLUMN IF NOT EXISTS payment_date    date NULL;

                        CREATE INDEX IF NOT EXISTS activities__is_recu_2e4401_idx
                            ON activities_activity (is_recurring);

                        CREATE INDEX IF NOT EXISTS activities__is_proc_90253d_idx
                            ON activities_activity (is_procurement);

                        CREATE INDEX IF NOT EXISTS activities__parent__a29af9_idx
                            ON activities_activity (parent_activity_id);

                        CREATE INDEX IF NOT EXISTS activities__recurre_479564_idx
                            ON activities_activity (recurrence_end_date);

                        CREATE INDEX IF NOT EXISTS activities__year_3dfddb_idx
                            ON activities_activity (year, planned_month);

                        CREATE INDEX IF NOT EXISTS activities__activit_3bf950_idx
                            ON activities_activityattachment (activity_id, is_latest);

                        CREATE INDEX IF NOT EXISTS activities__documen_d60465_idx
                            ON activities_activityattachment (document_type, is_deleted);

                        CREATE INDEX IF NOT EXISTS activities__uploade_215748_idx
                            ON activities_activityattachment (uploaded_at);

                        CREATE INDEX IF NOT EXISTS activities__activit_152f8a_idx
                            ON activities_notificationlog (activity_id, recipient_id);

                        CREATE INDEX IF NOT EXISTS activities__status_acb1cf_idx
                            ON activities_notificationlog (status, created_at);

                        CREATE INDEX IF NOT EXISTS activities__notific_d716d8_idx
                            ON activities_notificationlog (notification_type);
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
