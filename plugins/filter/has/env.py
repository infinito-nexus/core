from pathlib import Path


def has_env(application_id, base_dir="."):
    """
    Check if env.j2 exists under roles/{{ application_id }}/templates/env.j2
    """
    path = str(Path(base_dir) / "roles" / application_id / "templates" / "env.j2")
    return Path(path).is_file()


class FilterModule:
    def filters(self):
        return {
            "has_env": has_env,
        }
