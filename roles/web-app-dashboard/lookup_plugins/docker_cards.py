from __future__ import absolute_import, division, print_function

__metaclass__ = type

import glob
import os
import re

from ansible.plugins.lookup import LookupBase
from ansible.errors import AnsibleError
from utils.applications.config import get
from utils.cache.applications import get_merged_applications
from utils.cache.domains import get_merged_domains
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from ansible.plugins.loader import lookup_loader


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        """
        This lookup iterates over all roles whose folder name starts with 'web-app-'
        and generates a list of dictionaries (cards). For each role, it:

          - Reads application_id from the role's vars/main.yml
          - Reads the title from the role's README.md (the first H1 line)
          - Retrieves the description from galaxy_info.description in meta/main.yml
          - Retrieves the icon class from meta/info.yml.logo.class (req-011)
          - Retrieves the display flag from meta/info.yml.display (req-011)
          - Retrieves the tags from galaxy_info.galaxy_tags
          - Builds the URL using the 'domains' variable
          - Sets the iframe flag from applications

        Only cards whose application_id is included in the variable group_names are returned.
        """
        # Default to "roles" directory if no path is provided
        roles_dir = terms[0] if len(terms) > 0 else "roles"
        cards = []

        # Minimal: keep behavior but avoid None access
        variables = variables or {}

        # Retrieve group_names from variables (used to filter roles)
        group_names = variables.get("group_names", [])

        # Always re-derive applications from inventory + role defaults.
        # The raw `applications` variable may be an unrendered placeholder
        # inside nested template lookups, which silently makes
        # get(..., strict=False, default=False) return False.
        applications = get_merged_applications(
            variables=variables,
            roles_dir=roles_dir,
            templar=getattr(self, "_templar", None),
        )

        # Search for all roles starting with "web-app-"
        pattern = os.path.join(roles_dir, "web-app-*")
        for role_path in glob.glob(pattern):
            role_dir = role_path.rstrip("/")
            role_basename = os.path.basename(role_dir)

            # Skip roles not starting with "web-app-"
            if not role_basename.startswith("web-app-"):  # Ensure prefix
                continue

            # Load application_id from role's vars/main.yml (cached parse).
            vars_path = os.path.join(role_dir, "vars", "main.yml")
            try:
                if not os.path.isfile(vars_path):
                    raise AnsibleError(
                        f"Vars file not found for role '{role_basename}': {vars_path}"
                    )
                vars_data = load_yaml_any(vars_path, default_if_missing={}) or {}
                application_id = (
                    vars_data.get("application_id")
                    if isinstance(vars_data, dict)
                    else None
                )
                if not application_id:
                    raise AnsibleError(f"Key 'application_id' not found in {vars_path}")
            except Exception as e:
                raise AnsibleError(
                    f"Error getting application_id for role '{role_basename}': {e}"
                )

            # Skip roles not listed in group_names
            if application_id not in group_names:
                continue

            # Define paths to README.md, meta/main.yml and meta/info.yml.
            # meta/main.yml carries Galaxy-spec fields (description, galaxy_tags);
            # meta/info.yml is the project-internal store for descriptive
            # role-level metadata (logo, display) per req-011.
            readme_path = os.path.join(role_dir, "README.md")
            meta_path = os.path.join(role_dir, "meta", "main.yml")
            info_path = os.path.join(role_dir, "meta", "info.yml")

            # Skip role if required files are missing
            if not os.path.exists(readme_path) or not os.path.exists(meta_path):
                continue

            # Extract title from first H1 line in README.md (cached read).
            try:
                readme_content = read_text(readme_path)
                title_match = re.search(r"^#\s+(.*)$", readme_content, re.MULTILINE)
                title = title_match.group(1).strip() if title_match else application_id
            except Exception as e:
                raise AnsibleError(f"Error reading '{readme_path}': {e}")

            # Extract Galaxy-spec metadata from meta/main.yml (cached parse).
            try:
                meta_data = load_yaml_any(meta_path, default_if_missing={}) or {}
                galaxy_info = (
                    meta_data.get("galaxy_info", {})
                    if isinstance(meta_data, dict)
                    else {}
                )
                description = galaxy_info.get("description", "")
                tags = galaxy_info.get("galaxy_tags", [])
            except Exception as e:
                raise AnsibleError(f"Error reading '{meta_path}': {e}")

            # Extract project-internal descriptive metadata from meta/info.yml.
            # File-root convention: the file's content IS applications.<role>.info.
            info_data: dict = {}
            if os.path.isfile(info_path):
                try:
                    loaded = load_yaml_any(info_path, default_if_missing={}) or {}
                    info_data = loaded if isinstance(loaded, dict) else {}
                except Exception as e:
                    raise AnsibleError(f"Error reading '{info_path}': {e}")

            # If display is set to False ignore it (default: shown)
            if not info_data.get("display", True):
                continue

            logo = info_data.get("logo") or {}
            icon_class = logo.get("class", "fa-solid fa-cube")

            # Retrieve domains via cached merger; applications already merged above.
            domains = get_merged_domains(
                variables=variables,
                roles_dir=roles_dir,
                templar=getattr(self, "_templar", None),
            )
            domain_url = domains.get(application_id, "")

            if isinstance(domain_url, list):
                domain_url = domain_url[0]
            elif isinstance(domain_url, dict):
                domain_url = next(iter(domain_url.values()))

            # domain_url kann list/dict sein; nach deiner Normalisierung:
            domain_url = (
                self._templar.template(domain_url).strip() if domain_url else ""
            )

            # Build URL via strict tls resolver
            url = ""
            if domain_url:
                try:
                    tls_lookup = lookup_loader.get(
                        "tls", loader=self._loader, templar=self._templar
                    )
                    # tls: positional want-path API
                    base_url = tls_lookup.run(
                        [application_id, "url.base"], variables=variables
                    )[0]
                    url = str(base_url).strip().rstrip("/")
                except Exception as e:
                    raise AnsibleError(
                        f"Error building URL via tls for '{application_id}': {e}"
                    )

            iframe = get(
                applications,
                application_id,
                "services.dashboard.enabled",
                strict=False,
                default=False,
            )

            # Build card dictionary
            card = {
                "icon": {"class": icon_class},
                "title": title,
                "text": description,
                "url": url,
                "link_text": f"Explore {title}",
                "iframe": iframe,
                "tags": tags,
            }

            cards.append(card)

        # Sort A-Z
        cards.sort(key=lambda c: c["title"].lower())

        # Return the list of cards
        return [cards]
