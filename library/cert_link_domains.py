from pathlib import Path

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.cert_utils import CertUtils


def link_domain(domain, cert_base_path):
    link = Path(cert_base_path) / domain
    if link.is_dir() and not link.is_symlink():
        return "kept"
    folder = CertUtils.find_cert_for_domain(domain, cert_base_path)
    if folder is None:
        return "missing"
    if link.is_symlink() and str(link.readlink()) == folder:
        return "kept"
    staging = link.with_name(f"{domain}.link-tmp")
    staging.unlink(missing_ok=True)
    staging.symlink_to(folder)
    staging.replace(link)
    return "linked"


def main():
    module = AnsibleModule(
        argument_spec={
            "domains": {"type": "list", "elements": "str", "required": True},
            "cert_base_path": {"type": "str", "required": True},
        }
    )
    result = {"kept": [], "linked": [], "missing": []}
    for domain in module.params["domains"]:
        result[link_domain(domain, module.params["cert_base_path"])].append(domain)
    module.exit_json(changed=bool(result["linked"]), **result)


if __name__ == "__main__":
    main()
