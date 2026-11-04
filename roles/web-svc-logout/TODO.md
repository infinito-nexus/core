# Todos

- solve loading of domains which are not in group names, but declared via dependencies
- The conductor row of `https://api.seaweedfs.s3.<domain>` always ends in "Failed" while every other row signs out: on 2026-10-09 its `/logout` answered `403` with `content-type: application/xml` from the S3 API and without `access-control-allow-credentials`, so no logout location serves it. `LOGOUT_DOMAINS` in `vars/main.yml` (filter `logout_domains` in `filter_plugins/domain_filters.py`) lists every domain of a logout consumer, also one whose vhost does not render `roles/sys-front-inj-all/templates/server.conf.j2` with `templates/logout-proxy.conf.j2`. Options: leave such domains out of `LOGOUT_DOMAINS`, or include the logout location in the SeaweedFS S3 API vhost.
