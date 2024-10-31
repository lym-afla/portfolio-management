# Generated by Django 5.0.1 on 2024-10-30 22:38

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0045_fxtransaction_commission_currency_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(
            model_name='assets',
            name='investor',
        ),
        migrations.AddField(
            model_name='assets',
            name='investors',
            field=models.ManyToManyField(blank=True, related_name='assets', to=settings.AUTH_USER_MODEL),
        ),
    ]
