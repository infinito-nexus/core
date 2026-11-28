"""Converge ``auth_totp.policy``, the second-factor enforcement ``auth_totp_mail`` reads.

Env (from the container):
    ODOO_2FA_STATE   ``enforce`` (2fa on, enforced, mail deployed), ``offer``
                     (2fa on, not enforced), ``hold`` (enforced, but no mail
                     deployed) or ``off`` (the role's own 2fa is off)
    ODOO_2FA_POLICY  the value the deploy writes to enforce, such as ``all_required``

The parameter ``OWNER`` marks a policy the deploy switched on itself and keeps
the policy it replaced (``PRIOR_NONE`` when there was none). ``enforce`` opens
an SMTP session through ``ir.mail_server`` first, because ``auth_totp_mail``
mails the sign-in code: when that fails it refuses to switch the policy on, but
keeps a policy it already owns, so a passing outage drops no enforcement.
``offer``, ``hold`` and ``off`` restore the replaced policy only while the
marker is set and the policy still holds the deploy's value, so a policy an
admin chose stays.

Prints ``MAIL=ok`` or ``MAIL=failed <error class>`` after the SMTP test, then
``TWO_FACTOR_POLICY_CHANGED`` or ``TWO_FACTOR_POLICY_UNCHANGED``.
"""

import os

KEY = "auth_totp.policy"
OWNER = "infinito.auth_totp_policy_by_deploy"
PRIOR_NONE = "none"

env = globals()["env"]
state = os.environ["ODOO_2FA_STATE"]
policy = os.environ["ODOO_2FA_POLICY"]
parameters = env["ir.config_parameter"].sudo()
current = parameters.get_param(KEY) or False
marker = parameters.get_param(OWNER) or False
owned = bool(marker) and current == policy
prior = False if marker in (False, PRIOR_NONE) else marker


def open_smtp_session():
    smtp = env["ir.mail_server"]._connect__()
    if smtp is None:
        raise ConnectionError("no SMTP session")
    smtp.close()


if state == "enforce":
    try:
        open_smtp_session()
        print("MAIL=ok")
    except Exception as error:
        print(f"MAIL=failed {type(error).__name__}")
        state = "probe_failed"

if state == "enforce":
    wanted, mark = policy, marker if current == policy else current or PRIOR_NONE
elif state == "probe_failed":
    wanted, mark = current, marker if owned else False
elif owned:
    wanted, mark = prior, False
else:
    wanted, mark = current, False

if wanted != current or mark != marker:
    parameters.set_param(KEY, wanted)
    parameters.set_param(OWNER, mark)
    env.cr.commit()
    env.registry.signal_changes()
    print("TWO_FACTOR_POLICY_CHANGED")
else:
    print("TWO_FACTOR_POLICY_UNCHANGED")
