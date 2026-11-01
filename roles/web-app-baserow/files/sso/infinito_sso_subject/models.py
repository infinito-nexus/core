from django.conf import settings
from django.db import models


class SsoSubject(models.Model):
    """The Keycloak preferred_username a Baserow account signs in as.

    Baserow keys its accounts by email (its username is the email), so the
    SSO glue keeps the stable Keycloak username here and never looks an
    account up by address.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="infinito_sso_subject",
    )
    username = models.CharField(max_length=255, unique=True)
