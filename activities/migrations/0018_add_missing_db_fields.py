# On existing DBs this migration previously ran database_operations to fill in columns
# that 0002 had been fake-applied without executing. Those columns now exist in the DB.
# On a fresh install 0002 creates everything, so no DB work is needed here.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_coordinated_funder'),
        ('activities', '0017_sync_missing_fields'),
        ('masters', '0003_activitycategory_activitysubcategory'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(state_operations=[], database_operations=[]),
    ]
