"""Drop ``associate_by_email`` from Weblate's social auth pipeline.

``weblate/settings_docker.py`` runs this file through ``exec`` in its own module
namespace, after it built ``SOCIAL_AUTH_PIPELINE``; the pipeline therefore comes
from ``globals()`` and every other step keeps its upstream position.
"""

SOCIAL_AUTH_PIPELINE = [
    step
    for step in globals()["SOCIAL_AUTH_PIPELINE"]
    if step != "social_core.pipeline.social_auth.associate_by_email"
]
