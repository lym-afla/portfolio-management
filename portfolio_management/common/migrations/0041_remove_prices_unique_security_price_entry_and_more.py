# Generated by Django 5.0.1 on 2024-09-08 20:27

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0040_finalize_fx_id'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='prices',
            name='unique_security_price_entry',
        ),
        migrations.AlterField(
            model_name='fx',
            name='CHFGBP',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=8, null=True),
        ),
        migrations.AlterField(
            model_name='fx',
            name='PLNUSD',
            field=models.DecimalField(blank=True, decimal_places=5, max_digits=9, null=True),
        ),
        migrations.AlterField(
            model_name='fx',
            name='RUBUSD',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name='fx',
            name='USDEUR',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=8, null=True),
        ),
        migrations.AlterField(
            model_name='fx',
            name='USDGBP',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=8, null=True),
        ),
        migrations.AlterField(
            model_name='fx',
            name='date',
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name='fx',
            name='id',
            field=models.AutoField(primary_key=True, serialize=False),
        ),
        migrations.AlterUniqueTogether(
            name='fx',
            unique_together={('date', 'investor')},
        ),
        migrations.AddConstraint(
            model_name='prices',
            constraint=models.UniqueConstraint(fields=('date', 'security'), name='unique_security_price_entry'),
        ),
    ]