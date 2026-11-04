ARG ERPNEXT_IMAGE
ARG ERPNEXT_VERSION
FROM ${ERPNEXT_IMAGE}:${ERPNEXT_VERSION}

ARG ERPNEXT_LOGIN_RBAC_APP

COPY --chown=frappe:0 ${ERPNEXT_LOGIN_RBAC_APP} /home/frappe/frappe-bench/apps/${ERPNEXT_LOGIN_RBAC_APP}

RUN echo "/home/frappe/frappe-bench/apps/${ERPNEXT_LOGIN_RBAC_APP}" \
      > "$(/home/frappe/frappe-bench/env/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')/${ERPNEXT_LOGIN_RBAC_APP}.pth" \
    && /home/frappe/frappe-bench/env/bin/python -c "import ${ERPNEXT_LOGIN_RBAC_APP}.hooks"
