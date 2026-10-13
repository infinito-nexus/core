import base64
import json
import os
from pathlib import PurePosixPath

from django.core.files.uploadedfile import SimpleUploadedFile
from dynamic_preferences.registries import global_preferences_registry

FILE_PREFIX = "infinito-design-"

manager = global_preferences_registry.manager()
present = os.environ["FUNKWHALE_DESIGN_STATE"] == "present"
mark = os.environ["FUNKWHALE_DESIGN_MARK"]
strings = json.loads(os.environ["FUNKWHALE_DESIGN_STRINGS"])
files = json.loads(os.environ["FUNKWHALE_DESIGN_FILES"])

current_css = manager["ui__custom_css"] or ""
owned = current_css.startswith(mark) or (present and current_css == "")
changed = []


def ours(value):
    return bool(value) and PurePosixPath(value.name).name.startswith(FILE_PREFIX)


if owned:
    for name, value in strings.items():
        target = value if present else ""
        if manager[name] != target:
            manager[name] = target
            changed.append(name)
    for name, encoded in files.items():
        current = manager[name]
        data = base64.b64decode(encoded) if present and encoded else b""
        if data:
            if ours(current):
                with current.open("rb") as handle:
                    if handle.read() == data:
                        continue
            manager[name] = SimpleUploadedFile(
                FILE_PREFIX + name + ".png", data, content_type="image/png"
            )
            changed.append(name)
        elif ours(current):
            manager[name] = None
            changed.append(name)

if not owned and present:
    print("FUNKWHALE_DESIGN=FOREIGN")
elif changed:
    print("FUNKWHALE_DESIGN=CHANGED " + ",".join(changed))
else:
    print("FUNKWHALE_DESIGN=UNCHANGED")
