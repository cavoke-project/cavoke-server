# Generated by Django 2.2.3 on 2019-07-15 10:13

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cavoke_app', '0005_auto_20190715_1308'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='profile',
            name='uid',
        ),
    ]
