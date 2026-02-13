from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0004_owned_property"),
    ]

    operations = [
        migrations.AddField(
            model_name="ownedproperty",
            name="dispo",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="ownedproperty",
            name="area_m2",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
