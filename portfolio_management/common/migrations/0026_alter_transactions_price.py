# Generated by Django 5.0.1 on 2024-07-14 22:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0025_alter_assets_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transactions',
            name='price',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=15, null=True),
        ),
    ]
