from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0005_ownedproperty_dispo_area"),
    ]

    operations = [
        migrations.AddField(
            model_name="ownedproperty",
            name="purchase_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
