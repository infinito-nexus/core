# To-dos

- Move off PHP 7.4. The pinned `nfrastack/fusiondirectory:1.5` image builds on `ghcr.io/nfrastack/container-nginx-php-fpm` with PHP 7.4 on Alpine 3.15, which is end of life and gets no fix for CVE-2026-109618 and CVE-2026-109619.
- Mount the shared PHP hardening ini (`FILE_PHP_HARDENING_INI`) once the image's scan dir is verified. The nfrastack init scripts manage `conf.d` at runtime, so a read-only mount there has to be tested before it ships.
