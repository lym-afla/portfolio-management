# Generated by Django 5.0.1 on 2024-07-08 21:44

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0020_alter_annualperformance_unique_together_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='annualperformance',
            name='unique_investor_broker_year_currency',
        ),
        migrations.RemoveConstraint(
            model_name='annualperformance',
            name='unique_investor_broker_group_year_currency',
        ),
        migrations.AddConstraint(
            model_name='annualperformance',
            constraint=models.UniqueConstraint(fields=('investor', 'year', 'currency', 'broker'), name='unique_investor_broker_year_currency'),
        ),
        migrations.AddConstraint(
            model_name='annualperformance',
            constraint=models.UniqueConstraint(fields=('investor', 'year', 'currency', 'broker_group'), name='unique_investor_broker_group_year_currency'),
        ),
    ]
