"""Configure a dedicated Ubuntu 24 Squid HTTPS proxy; never contact a broker.

Run only on the dedicated proxy VM after installing squid-openssl and obtaining
the trendforge-kite-proxy Certbot certificate. Credentials stay in a root-only
file. This installer never changes a cloud firewall, SSH or trading flags.
"""

from __future__ import annotations

import argparse
import grp
import ipaddress
import json
import os
import secrets
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

DIRECTORY = Path("/etc/squid/trendforge")
LINEAGE = Path("/etc/letsencrypt/live/trendforge-kite-proxy")
MAIN_CONFIG = Path("/etc/squid/squid.conf")
PRIVATE_ENV = Path("/root/trendforge-kite-proxy.env")
INSTALLED_SCRIPT = Path("/usr/local/lib/trendforge-kite-proxy/configure.py")
HOOK = Path("/etc/letsencrypt/renewal-hooks/deploy/50-trendforge-kite-proxy")
DROP_IN = Path("/etc/systemd/system/squid.service.d/50-trendforge-ipv4.conf")
BACKUP = Path("/etc/squid/squid.conf.before-trendforge")
OS_RELEASE = Path("/etc/os-release")
AUTH_HELPER = Path("/usr/lib/squid/basic_ncsa_auth")
PORT = 8443


class SetupError(Exception):
    pass


def command(arguments: list[str], *, input_text: str | None = None) -> str:
    try:
        result = subprocess.run(
            arguments,
            input=input_text,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        # Command input can include the generated password. Never print it or
        # a raw exception/traceback. Inspect service logs locally when needed.
        raise SetupError("A prerequisite or proxy command failed") from None
    return result.stdout


def public_ipv4(value: str) -> str:
    try:
        address = ipaddress.IPv4Address(value)
        if not address.is_global:
            raise ValueError
        return str(address)
    except ValueError:
        raise SetupError("A dedicated public IPv4 address is required") from None


def atomic_write(path: Path, data: bytes, *, mode: int, gid: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), 0, gid)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def squid_configuration() -> str:
    return "\n".join(
        [
            "# Managed by Trendforge's dedicated proxy installer.",
            "visible_hostname trendforge-kite-egress",
            "https_port 0.0.0.0:8443 "
            "tls-cert=/etc/squid/trendforge/fullchain.pem "
            "tls-key=/etc/squid/trendforge/privkey.pem",
            "auth_param basic program /usr/lib/squid/basic_ncsa_auth "
            "/etc/squid/trendforge/passwords",
            "auth_param basic realm Trendforge-private-proxy",
            "auth_param basic credentialsttl 30 minutes",
            "acl tf_connect method CONNECT",
            "acl tf_tls_port port 443",
            "acl tf_hosts dstdomain -n "
            "api.kite.trade api4.ipify.org checkip.amazonaws.com",
            "acl tf_authenticated proxy_auth REQUIRED",
            "acl tf_private dst 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8",
            "acl tf_private dst 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16",
            "acl tf_private dst 224.0.0.0/4 240.0.0.0/4",
            "http_access deny !tf_connect",
            "http_access deny !tf_tls_port",
            "http_access deny !tf_hosts",
            "http_access deny !tf_authenticated",
            "http_access deny tf_private",
            "http_access allow tf_authenticated",
            "http_access deny all",
            "cache deny all",
            "access_log none",
            "forwarded_for delete",
            "shutdown_lifetime 3 seconds",
            "",
        ]
    )


def validate_certificate(ip: str) -> None:
    certificate = str(LINEAGE / "fullchain.pem")
    private_key = str(LINEAGE / "privkey.pem")
    command(["openssl", "x509", "-in", certificate, "-noout", "-checkip", ip])
    command(["openssl", "x509", "-in", certificate, "-noout", "-checkend", "86400"])
    command(
        [
            "openssl",
            "verify",
            "-purpose",
            "sslserver",
            "-verify_ip",
            ip,
            "-untrusted",
            certificate,
            certificate,
        ]
    )
    certificate_key = command(
        ["openssl", "x509", "-in", certificate, "-pubkey", "-noout"]
    )
    actual_key = command(["openssl", "pkey", "-in", private_key, "-pubout"])
    if certificate_key.strip() != actual_key.strip():
        raise SetupError("Certificate and private key do not match")


def sync_certificates(ip: str, *, reload_service: bool) -> None:
    validate_certificate(ip)
    gid = grp.getgrnam("proxy").gr_gid
    # Read both validated files before replacing either installed file.
    replacements = {
        name: (LINEAGE / name).read_bytes() for name in ("fullchain.pem", "privkey.pem")
    }
    previous = {
        name: (DIRECTORY / name).read_bytes() if (DIRECTORY / name).exists() else None
        for name in replacements
    }
    try:
        for name, data in replacements.items():
            atomic_write(DIRECTORY / name, data, mode=0o640, gid=gid)
        if reload_service:
            command(["/usr/sbin/squid", "-k", "parse"])
            command(["systemctl", "reload", "squid"])
    except (OSError, SetupError):
        for name, data in previous.items():
            if data is not None:
                atomic_write(DIRECTORY / name, data, mode=0o640, gid=gid)
        raise SetupError("Certificate reload failed; previous files restored") from None


def private_environment(ip: str, password: str) -> str:
    authority = "trendforge:" + password + "@" + ip + ":" + str(PORT)
    return (
        "TRENDFORGE_KITE_PROXY_URL=https://"
        + authority
        + "\n"
        + "TRENDFORGE_KITE_EGRESS_IPS="
        + ip
        + "\n"
        + "TRENDFORGE_KITE_NETWORK_PROBE_ON_START=true\n"
        + "TRENDFORGE_LIVE_TRADING_ENABLED=false\n"
        + "TRENDFORGE_OWNER_KITE_ORDER_TEST=\n"
    )


def configure(ip: str) -> None:
    ip = public_ipv4(ip)
    if DIRECTORY.exists() or PRIVATE_ENV.exists() or PRIVATE_ENV.is_symlink():
        raise SetupError("Existing setup detected; credentials will not be overwritten")
    os_release = OS_RELEASE.read_text()
    if "ID=ubuntu" not in os_release or 'VERSION_ID="24.04"' not in os_release:
        raise SetupError("This installer requires the dedicated Ubuntu 24.04 VM")
    version = command(["/usr/sbin/squid", "-v"])
    if "--with-openssl" not in version:
        raise SetupError("Install the squid-openssl package first")
    if not AUTH_HELPER.is_file():
        raise SetupError("Squid's authentication helper is missing")
    try:
        command(["systemctl", "is-active", "--quiet", "snap.certbot.renew.timer"])
    except SetupError:
        raise SetupError("Certbot's snap.certbot.renew.timer must be active") from None
    validate_certificate(ip)
    gid = grp.getgrnam("proxy").gr_gid
    if BACKUP.exists():
        raise SetupError("A prior configuration backup exists; inspect it first")
    if MAIN_CONFIG.exists():
        atomic_write(BACKUP, MAIN_CONFIG.read_bytes(), mode=0o600)
    command(["systemctl", "stop", "squid"])
    try:
        DIRECTORY.mkdir(mode=0o750)
        os.chown(DIRECTORY, 0, gid)
        password = secrets.token_hex(24)
        command(
            [
                "htpasswd",
                "-icB",
                "-C",
                "12",
                str(DIRECTORY / "passwords"),
                "trendforge",
            ],
            input_text=password + "\n",
        )
        os.chown(DIRECTORY / "passwords", 0, gid)
        os.chmod(DIRECTORY / "passwords", 0o640)
        sync_certificates(ip, reload_service=False)
        atomic_write(MAIN_CONFIG, squid_configuration().encode(), mode=0o644)
        # Restrict only this service, keeping the VM's SSH/network unchanged.
        # No IPv6 socket can bypass the whitelisted public IPv4 route.
        atomic_write(
            DROP_IN,
            b"[Service]\nRestrictAddressFamilies=\n"
            b"RestrictAddressFamilies=AF_UNIX AF_INET AF_NETLINK\n",
            mode=0o644,
        )
        atomic_write(INSTALLED_SCRIPT, Path(__file__).read_bytes(), mode=0o644)
        atomic_write(
            DIRECTORY / "state.json",
            json.dumps({"ip": ip}).encode(),
            mode=0o640,
            gid=gid,
        )
        hook = (
            "#!/bin/sh\nset -eu\n"
            'if [ "${RENEWED_LINEAGE:-}" = "' + str(LINEAGE) + '" ]; then\n'
            "    /usr/bin/python3 " + str(INSTALLED_SCRIPT) + " --renew\nfi\n"
        )
        atomic_write(HOOK, hook.encode(), mode=0o755)
        atomic_write(
            PRIVATE_ENV, private_environment(ip, password).encode(), mode=0o600
        )
        command(["systemctl", "daemon-reload"])
        command(["/usr/sbin/squid", "-k", "parse"])
        command(["systemctl", "enable", "--now", "squid"])
        command(["systemctl", "is-active", "--quiet", "squid"])
    except (OSError, SetupError):
        with suppress(SetupError):
            command(["systemctl", "stop", "squid"])
        raise SetupError(
            "Setup stopped; inspect local Squid logs before retrying"
        ) from None
    print("Proxy configured and service active on IPv4 TLS port 8443.")
    print("Credentials saved privately in /root/trendforge-kite-proxy.env.")
    print("No cloud firewall, Kite whitelist or broker order was changed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--configure", metavar="PUBLIC_IPV4")
    mode.add_argument("--renew", action="store_true")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise SetupError("Run this dedicated-host installer with sudo")
        if args.renew:
            state = json.loads((DIRECTORY / "state.json").read_text())
            sync_certificates(public_ipv4(state["ip"]), reload_service=True)
        else:
            configure(args.configure)
    except SetupError as error:
        print(str(error) + ". No credentials are printed.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError):
        print(
            "Proxy setup/check failed. Keep the proxy firewall port closed and "
            "inspect the local service logs. No credentials are printed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
