from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('activities', '0011_activity_deleted_alter_activity_retired'),
    ]

    operations = [
        migrations.AddField(
            model_name='activity',
            name='category',
            field=models.JSONField(blank=True, default=list, help_text='Activity categories'),
        ),
    ]
