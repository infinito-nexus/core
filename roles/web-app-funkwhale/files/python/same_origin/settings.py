from config.settings.production import *  # noqa: F403

STORAGES["default"]["BACKEND"] = "same_origin_storage.SameOriginS3Storage"  # noqa: F405
ROOT_URLCONF = "same_origin_urls"
