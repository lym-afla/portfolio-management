# Generated by Django 5.0.1 on 2024-08-06 20:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_alter_customuser_default_currency'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customuser',
            name='default_currency',
            field=models.CharField(blank=True, choices=[('USD', '$'), ('EUR', '€'), ('GBP', '£'), ('RUB', '₽'), ('CHF', '₣')], default='USD', max_length=3, null=True),
        ),
    ]
