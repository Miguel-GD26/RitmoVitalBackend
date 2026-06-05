from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classifier', '0012_userprofile_totp_enabled_userprofile_totp_secret_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='email_verified',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='must_change_password',
            field=models.BooleanField(default=False),
        ),
    ]
