import base64
import json
import os
from pathlib import PurePosixPath

from django.core.files.uploadedfile import SimpleUploadedFile
from dynamic_preferences.registries import global_preferences_registry

FILE_PREFIX = "infinito-design-"
NAME = "instance__name"

mode = os.environ["FUNKWHALE_DESIGN_MODE"]
if mode not in ("read", "converge"):
    raise ValueError("FUNKWHALE_DESIGN_MODE must be read or converge")
apply = mode == "converge"
manager = global_preferences_registry.manager()
present = os.environ["FUNKWHALE_DESIGN_STATE"] == "present"
mark = os.environ["FUNKWHALE_DESIGN_MARK"]
strings = json.loads(os.environ["FUNKWHALE_DESIGN_STRINGS"])
files = json.loads(os.environ["FUNKWHALE_DESIGN_FILES"])

current_css = manager["ui__custom_css"] or ""
owned = current_css.startswith(mark) or (present and current_css == "")
stored_name = manager[NAME] or ""
enforced = {NAME} if present else set()
changed = []


def ours(value):
    return bool(value) and PurePosixPath(value.name).name.startswith(FILE_PREFIX)


def write(name, value):
    if apply:
        manager[name] = value
    changed.append(name)


for name in enforced & set(strings):
    if manager[name] != strings[name]:
        write(name, strings[name])

if owned:
    for name, value in strings.items():
        target = value if present else ""
        if name not in enforced and manager[name] != target:
            write(name, target)
    for name, encoded in files.items():
        current = manager[name]
        data = base64.b64decode(encoded) if present and encoded else b""
        if data:
            if ours(current):
                with current.open("rb") as handle:
                    if handle.read() == data:
                        continue
            write(
                name,
                SimpleUploadedFile(
                    FILE_PREFIX + name + ".png", data, content_type="image/png"
                ),
            )
        elif ours(current):
            write(name, None)

if not apply:
    print(json.dumps({"pending": bool(changed), "instance_name": stored_name}))
elif changed:
    print("FUNKWHALE_DESIGN=CHANGED " + ",".join(changed))
elif not owned and present:
    print("FUNKWHALE_DESIGN=FOREIGN")
else:
    print("FUNKWHALE_DESIGN=UNCHANGED")
