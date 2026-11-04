from typing import ClassVar

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: ClassVar[list] = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL)
    ]

    operations: ClassVar[list] = [
        migrations.CreateModel(
            name="SsoSubject",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("username", models.CharField(max_length=255, unique=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="infinito_sso_subject",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
