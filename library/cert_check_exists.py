from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.cert_utils import CertUtils


def main():
    module_args = {
        "domain": {"type": "str", "required": True},
        "cert_base_path": {
            "type": "str",
            "required": False,
            "default": "/etc/letsencrypt/live",
        },
        "debug": {"type": "bool", "required": False, "default": False},
    }

    module = AnsibleModule(argument_spec=module_args)

    domain = module.params["domain"]
    cert_base_path = module.params["cert_base_path"]
    debug = module.params["debug"]

    folder = CertUtils.find_cert_for_domain(domain, cert_base_path, debug)
    exists = folder is not None

    module.exit_json(exists=exists)


if __name__ == "__main__":
    main()
