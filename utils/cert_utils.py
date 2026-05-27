#!/usr/bin/env python3


import os
import subprocess
from datetime import UTC, datetime


class CertUtils:
    _domain_cert_mapping = None
    _cert_snapshot = None

    @staticmethod
    def run_openssl(cert_path):
        try:
            return subprocess.check_output(
                ["openssl", "x509", "-in", cert_path, "-noout", "-text"],
                universal_newlines=True,
            )
        except subprocess.CalledProcessError:
            return ""

    @staticmethod
    def run_openssl_dates(cert_path):
        """
        Returns (not_before_ts, not_after_ts) as POSIX timestamps or (None, None) on failure.
        """
        try:
            output = subprocess.check_output(
                [
                    "openssl",
                    "x509",
                    "-in",
                    cert_path,
                    "-noout",
                    "-startdate",
                    "-enddate",
                ],
                universal_newlines=True,
            )
            nb, na = None, None
            for raw_line in output.splitlines():
                line = raw_line.strip()
                if line.startswith("notBefore="):
                    nb = line.split("=", 1)[1].strip()
                elif line.startswith("notAfter="):
                    na = line.split("=", 1)[1].strip()

            def _parse(openssl_dt):
                # OpenSSL format example: "Oct 10 12:34:56 2025 GMT".
                # ``%Z`` parses the literal "GMT" but produces a naive
                # datetime; openssl always emits GMT, so we anchor the
                # parsed value to UTC explicitly to make it tz-aware.
                naive = datetime.strptime(  # noqa: DTZ007  %Z parses GMT abbrev; openssl always emits UTC, anchored below
                    openssl_dt, "%b %d %H:%M:%S %Y %Z"
                )
                return int(naive.replace(tzinfo=UTC).timestamp())

            return (_parse(nb) if nb else None, _parse(na) if na else None)
        except Exception:
            return (None, None)

    @staticmethod
    def extract_sans(cert_text):
        dns_entries = []
        in_san = False
        for raw_line in cert_text.splitlines():
            line = raw_line.strip()
            if "X509v3 Subject Alternative Name:" in line:
                in_san = True
                continue
            if in_san:
                if not line:
                    break
                dns_entries += [
                    e.strip().replace("DNS:", "") for e in line.split(",") if e.strip()
                ]
        return dns_entries

    @staticmethod
    def list_cert_files(cert_base_path):
        cert_files = []
        for root, _dirs, files in os.walk(cert_base_path):
            if "cert.pem" in files:
                cert_files.append(os.path.join(root, "cert.pem"))
        return cert_files

    @staticmethod
    def matches(domain, san):
        """RFC compliant SAN matching."""
        if san.startswith("*."):
            base = san[2:]
            # Wildcard matches ONLY one additional label
            if domain == base:
                return False
            return bool(
                domain.endswith("." + base) and domain.count(".") == base.count(".") + 1
            )
        return domain == san

    @classmethod
    def build_snapshot(cls, cert_base_path):
        snapshot = []
        for cert_file in cls.list_cert_files(cert_base_path):
            try:
                stat = os.stat(cert_file)
                snapshot.append((cert_file, stat.st_mtime, stat.st_size))
            except FileNotFoundError:
                continue
        snapshot.sort()
        return snapshot

    @classmethod
    def snapshot_changed(cls, cert_base_path):
        current_snapshot = cls.build_snapshot(cert_base_path)
        if cls._cert_snapshot != current_snapshot:
            cls._cert_snapshot = current_snapshot
            return True
        return False

    @classmethod
    def refresh_cert_mapping(cls, cert_base_path, debug=False):
        """
        Build mapping: SAN -> list of entries
        entry = {
            'folder': str,
            'cert_path': str,
            'mtime': float,
            'not_before': int|None,
            'not_after': int|None,
            'is_wildcard': bool
        }
        """
        cert_files = cls.list_cert_files(cert_base_path)
        mapping = {}
        for cert_path in cert_files:
            cert_text = cls.run_openssl(cert_path)
            if not cert_text:
                continue
            sans = cls.extract_sans(cert_text)
            folder = os.path.basename(os.path.dirname(cert_path))
            try:
                mtime = os.stat(cert_path).st_mtime
            except FileNotFoundError:
                mtime = 0.0
            nb, na = cls.run_openssl_dates(cert_path)

            for san in sans:
                entry = {
                    "folder": folder,
                    "cert_path": cert_path,
                    "mtime": mtime,
                    "not_before": nb,
                    "not_after": na,
                    "is_wildcard": san.startswith("*."),
                }
                mapping.setdefault(san, []).append(entry)

        cls._domain_cert_mapping = mapping
        if debug:
            print(
                f"[DEBUG] Refreshed domain-to-cert mapping (counts): "
                f"{ {k: len(v) for k, v in mapping.items()} }"
            )

    @classmethod
    def ensure_cert_mapping(cls, cert_base_path, debug=False):
        if cls._domain_cert_mapping is None or cls.snapshot_changed(cert_base_path):
            cls.refresh_cert_mapping(cert_base_path, debug)

    @staticmethod
    def _score_entry(entry):
        """
        Return tuple used for sorting newest-first:
        (not_before or -inf, mtime)
        """
        nb = entry.get("not_before")
        mtime = entry.get("mtime", 0.0)
        return (nb if nb is not None else -1, mtime)

    @classmethod
    def find_cert_for_domain(cls, domain, cert_base_path, debug=False):
        cls.ensure_cert_mapping(cert_base_path, debug)

        candidates_exact = []
        candidates_wild = []

        for san, entries in cls._domain_cert_mapping.items():
            if san == domain:
                candidates_exact.extend(entries)
            elif san.startswith("*."):
                base = san[2:]
                if domain.count(".") == base.count(".") + 1 and domain.endswith(
                    "." + base
                ):
                    candidates_wild.extend(entries)

        def _pick_newest(entries):
            if not entries:
                return None
            # newest by (not_before, mtime)
            return max(entries, key=cls._score_entry)

        best_exact = _pick_newest(candidates_exact)
        best_wild = _pick_newest(candidates_wild)

        if best_exact and debug:
            print(
                f"[DEBUG] Best exact match for {domain}: {best_exact['folder']} "
                f"(not_before={best_exact['not_before']}, mtime={best_exact['mtime']})"
            )
        if best_wild and debug:
            print(
                f"[DEBUG] Best wildcard match for {domain}: {best_wild['folder']} "
                f"(not_before={best_wild['not_before']}, mtime={best_wild['mtime']})"
            )

        # Prefer exact if it exists; otherwise wildcard
        chosen = best_exact or best_wild

        if chosen:
            return chosen["folder"]

        if debug:
            print(f"[DEBUG] No certificate folder found for {domain}")

        return None
