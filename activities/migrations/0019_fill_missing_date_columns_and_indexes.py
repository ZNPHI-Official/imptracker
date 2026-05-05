# Migration 0002 was registered without executing its SQL (fake-applied).
# This migration adds the remaining columns and indexes that landed in the model
# via 0002 but were never written to the database.
# state_operations=[] throughout because 0002 already owns the migration state.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('activities', '0018_add_missing_db_fields'),
    ]

    operations = [
        # ----------------------------------------------------------------
        # Missing date columns on activities_activity
        # ----------------------------------------------------------------
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.AddField(
                    model_name='activity',
                    name='tendering_date',
                    field=models.DateField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name='activity',
                    name='order_date',
                    field=models.DateField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name='activity',
                    name='delivery_date',
                    field=models.DateField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name='activity',
                    name='payment_date',
                    field=models.DateField(blank=True, null=True),
                ),
            ],
        ),

        # ----------------------------------------------------------------
        # Missing indexes from 0002 (activities_activity)
        # ----------------------------------------------------------------
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.AddIndex(
                    model_name='activity',
                    index=models.Index(fields=['is_recurring'], name='activities__is_recu_2e4401_idx'),
                ),
                migrations.AddIndex(
                    model_name='activity',
                    index=models.Index(fields=['is_procurement'], name='activities__is_proc_90253d_idx'),
                ),
                migrations.AddIndex(
                    model_name='activity',
                    index=models.Index(fields=['parent_activity'], name='activities__parent__a29af9_idx'),
                ),
                migrations.AddIndex(
                    model_name='activity',
                    index=models.Index(fields=['recurrence_end_date'], name='activities__recurre_479564_idx'),
                ),
                migrations.AddIndex(
                    model_name='activity',
                    index=models.Index(fields=['year', 'planned_month'], name='activities__year_3dfddb_idx'),
                ),
            ],
        ),

        # ----------------------------------------------------------------
        # Missing indexes from 0002 (activities_activityattachment)
        # ----------------------------------------------------------------
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.AddIndex(
                    model_name='activityattachment',
                    index=models.Index(fields=['activity', 'is_latest'], name='activities__activit_3bf950_idx'),
                ),
                migrations.AddIndex(
                    model_name='activityattachment',
                    index=models.Index(fields=['document_type', 'is_deleted'], name='activities__documen_d60465_idx'),
                ),
                migrations.AddIndex(
                    model_name='activityattachment',
                    index=models.Index(fields=['uploaded_at'], name='activities__uploade_215748_idx'),
                ),
            ],
        ),

        # ----------------------------------------------------------------
        # Missing indexes from 0002 (activities_notificationlog)
        # ----------------------------------------------------------------
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.AddIndex(
                    model_name='notificationlog',
                    index=models.Index(fields=['activity', 'recipient'], name='activities__activit_152f8a_idx'),
                ),
                migrations.AddIndex(
                    model_name='notificationlog',
                    index=models.Index(fields=['status', 'created_at'], name='activities__status_acb1cf_idx'),
                ),
                migrations.AddIndex(
                    model_name='notificationlog',
                    index=models.Index(fields=['notification_type'], name='activities__notific_d716d8_idx'),
                ),
            ],
        ),
    ]
