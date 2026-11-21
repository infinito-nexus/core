import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

AUTH_USER_MODEL = "auth.User"


class Field(SimpleNamespace):
    """A Django field stub that records its constructor arguments.

    Args:
        kind: the field class name.
        args: positional constructor arguments.
        kwargs: keyword constructor arguments.
    """

    def __init__(self, kind, *args, **kwargs):
        super().__init__(kind=kind, args=args, kwargs=kwargs)


def _field(kind):
    return lambda *args, **kwargs: Field(kind, *args, **kwargs)


def load(app: Path, relative: str) -> ModuleType:
    """Execute a Django app module against Django stubs.

    Args:
        app: the app directory.
        relative: the module path below ``app``.

    Returns:
        The executed module.
    """
    deletion = ModuleType("django.db.models.deletion")
    deletion.CASCADE = "CASCADE"
    models = ModuleType("django.db.models")
    models.Model = object
    models.CASCADE = deletion.CASCADE
    models.deletion = deletion
    for kind in ("AutoField", "CharField", "OneToOneField"):
        setattr(models, kind, _field(kind))
    migrations = ModuleType("django.db.migrations")
    migrations.Migration = object
    migrations.CreateModel = lambda **kwargs: SimpleNamespace(
        operation="CreateModel", **kwargs
    )
    migrations.swappable_dependency = lambda model: ("__setting__", model)
    db = ModuleType("django.db")
    db.models = models
    db.migrations = migrations
    conf = ModuleType("django.conf")
    conf.settings = SimpleNamespace(AUTH_USER_MODEL=AUTH_USER_MODEL)
    django = ModuleType("django")
    django.db = db
    django.conf = conf
    stubs = {
        "django": django,
        "django.conf": conf,
        "django.db": db,
        "django.db.models": models,
        "django.db.models.deletion": deletion,
        "django.db.migrations": migrations,
    }
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location(
            f"{app.name}_{relative.replace('/', '_')}", app / relative
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module
