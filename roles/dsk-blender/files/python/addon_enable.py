"""Enable one legacy add-on in Blender's saved preferences, once.

Runs inside Blender through ``blender --background --python-expr``. Enabling an
add-on that the preferences already carry would rewrite userpref.blend on every
deploy, so the preferences are only saved when the module was absent.

Args:
    argv after "--": the add-on module to enable.

Output:
    ``ADDON=present`` when the saved preferences already carry the module,
    ``ADDON=enabled`` after enabling it and saving the preferences.
"""

import sys

import addon_utils
import bpy


def enable(module):
    preferences = bpy.context.preferences
    if module in preferences.addons:
        return "present"
    addon_utils.enable(module, default_set=True, persistent=True)
    if module not in preferences.addons:
        raise RuntimeError(f"Blender refused to enable the add-on {module}")
    bpy.ops.wm.save_userpref()
    return "enabled"


if __name__ == "__main__":
    print("ADDON=" + enable(sys.argv[sys.argv.index("--") + 1]))
