# Generated by Django 5.0.1 on 2024-08-08 18:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0033_assets_update_link_alter_annualperformance_currency_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='assets',
            name='data_source',
            field=models.CharField(choices=[('FT', 'Financial Times'), ('YAHOO', 'Yahoo Finance')], default='YAHOO', max_length=10),
        ),
        migrations.AddField(
            model_name='assets',
            name='yahoo_symbol',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
