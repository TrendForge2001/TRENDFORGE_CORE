"""Dedicated-host setup contracts; no root service or network is used in tests."""

import importlib
import json
import os
import re
import secrets
import shutil
import subprocess
from types import SimpleNamespace

import pytest

if os.name == "nt":
    pytest.skip("Dedicated proxy installation requires Unix", allow_module_level=True)

setup = importlib.import_module("scripts.configure_kite_proxy")


@pytest.fixture
def host(tmp_path, monkeypatch):
    for name in (
        "DIRECTORY",
        "LINEAGE",
        "MAIN_CONFIG",
        "PRIVATE_ENV",
        "INSTALLED_SCRIPT",
        "HOOK",
        "DROP_IN",
        "BACKUP",
        "OS_RELEASE",
        "AUTH_HELPER",
    ):
        original = getattr(setup, name)
        path = tmp_path / str(original).lstrip("/")
        monkeypatch.setattr(setup, name, path)
    setup.OS_RELEASE.parent.mkdir(parents=True)
    setup.OS_RELEASE.write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
    setup.AUTH_HELPER.parent.mkdir(parents=True)
    setup.AUTH_HELPER.touch()
    setup.MAIN_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    setup.MAIN_CONFIG.write_text("original dedicated-host configuration")
    setup.LINEAGE.mkdir(parents=True)
    (setup.LINEAGE / "fullchain.pem").write_bytes(b"new certificate")
    (setup.LINEAGE / "privkey.pem").write_bytes(b"new private key")
    monkeypatch.setattr(setup.os, "chown", lambda *args: None)
    monkeypatch.setattr(setup.os, "fchown", lambda *args: None)
    monkeypatch.setattr(setup.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=0))
    calls = []
    failures = set()

    def command(arguments, *, input_text=None):
        calls.append(tuple(arguments))
        if tuple(arguments) in failures:
            raise setup.SetupError("Simulated prerequisite failure")
        if arguments[:2] == ["/usr/sbin/squid", "-v"]:
            return "Squid 6.14 --with-openssl"
        if arguments[0] == "openssl" and "-pubkey" in arguments:
            return "same public key"
        if arguments[0] == "openssl" and "-pubout" in arguments:
            return "same public key"
        if arguments[0] == "htpasswd":
            assert input_text and len(input_text.strip()) == 48
            (setup.DIRECTORY / "passwords").write_text("synthetic hash")
        return ""

    monkeypatch.setattr(setup, "command", command)
    return SimpleNamespace(calls=calls, failures=failures)


@pytest.mark.parametrize("bad", ["127.0.0.1", "172.26.15.59", "::1", "not-an-ip"])
def test_nonpublic_or_nonipv4_address_is_rejected_before_changes(host, bad):
    with pytest.raises(setup.SetupError, match="public IPv4"):
        setup.configure(bad)
    assert host.calls == []
    assert not setup.DIRECTORY.exists()


def test_setup_preserves_backup_and_keeps_credentials_out_of_commands_and_output(
    host, capsys
):
    setup.configure("1.1.1.1")
    assert setup.BACKUP.read_text() == "original dedicated-host configuration"
    assert setup.PRIVATE_ENV.stat().st_mode & 0o777 == 0o600
    assert (setup.DIRECTORY / "privkey.pem").stat().st_mode & 0o777 == 0o640
    assert (setup.DIRECTORY / "passwords").stat().st_mode & 0o777 == 0o640
    private = setup.PRIVATE_ENV.read_text()
    password = re.search(r"trendforge:([a-f0-9]{48})@", private).group(1)
    assert password not in str(host.calls)
    assert password not in capsys.readouterr().out
    assert "TRENDFORGE_LIVE_TRADING_ENABLED=false" in private
    assert "TRENDFORGE_OWNER_KITE_ORDER_TEST=\n" in private
    assert setup.DROP_IN.read_text().splitlines() == [
        "[Service]",
        "RestrictAddressFamilies=",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_NETLINK",
    ]
    assert "--renew" in setup.HOOK.read_text()
    assert str(setup.LINEAGE) in setup.HOOK.read_text()
    parse = host.calls.index(("/usr/sbin/squid", "-k", "parse"))
    start = host.calls.index(("systemctl", "enable", "--now", "squid"))
    assert parse < start
    before = setup.PRIVATE_ENV.read_bytes()
    with pytest.raises(setup.SetupError, match="not be overwritten"):
        setup.configure("1.1.1.1")
    assert setup.PRIVATE_ENV.read_bytes() == before


def test_inactive_renewal_timer_cannot_start_proxy(host):
    host.failures.add(("systemctl", "is-active", "--quiet", "snap.certbot.renew.timer"))
    with pytest.raises(setup.SetupError):
        setup.configure("1.1.1.1")
    assert not setup.DIRECTORY.exists()
    assert not any("enable" in call for call in host.calls)


def test_parse_failure_stops_service_and_does_not_enable_it(host):
    host.failures.add(("/usr/sbin/squid", "-k", "parse"))
    with pytest.raises(setup.SetupError, match="Setup stopped"):
        setup.configure("1.1.1.1")
    assert host.calls[-1] == ("systemctl", "stop", "squid")
    assert not any("enable" in call for call in host.calls)


def test_renewal_parse_failure_restores_previous_certificates(host):
    setup.DIRECTORY.mkdir()
    (setup.DIRECTORY / "fullchain.pem").write_bytes(b"previous certificate")
    (setup.DIRECTORY / "privkey.pem").write_bytes(b"previous key")
    host.failures.add(("/usr/sbin/squid", "-k", "parse"))
    with pytest.raises(setup.SetupError, match="previous files restored"):
        setup.sync_certificates("1.1.1.1", reload_service=True)
    assert (setup.DIRECTORY / "fullchain.pem").read_bytes() == b"previous certificate"
    assert (setup.DIRECTORY / "privkey.pem").read_bytes() == b"previous key"
    assert ("systemctl", "reload", "squid") not in host.calls


def test_proxy_is_authenticated_tls_only_and_has_no_arbitrary_destination_rule():
    configuration = setup.squid_configuration()
    assert "http_port " not in configuration
    assert "https_port 0.0.0.0:8443" in configuration
    assert "ssl_bump" not in configuration
    assert "http_access allow all" not in configuration
    assert configuration.index("deny !tf_authenticated") < configuration.index(
        "allow tf_authenticated"
    )
    assert configuration.index("deny tf_private") < configuration.index(
        "allow tf_authenticated"
    )
    assert "port 443\n" in configuration
    assert "api.kite.trade api4.ipify.org checkip.amazonaws.com" in configuration
    assert "access_log none" in configuration


def test_failed_subprocess_never_exposes_private_input(monkeypatch):
    private = secrets.token_hex(24)

    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], output=private)

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(setup.SetupError) as failure:
        setup.command(["htpasswd"], input_text=private)
    assert private not in str(failure.value)


def test_renewal_uses_the_saved_public_ip_and_never_starts_a_new_setup(
    host, monkeypatch
):
    setup.DIRECTORY.mkdir()
    (setup.DIRECTORY / "state.json").write_text(json.dumps({"ip": "1.1.1.1"}))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr("sys.argv", ["configure_kite_proxy.py", "--renew"])
    assert setup.main() == 0
    assert ("systemctl", "reload", "squid") in host.calls
    assert not any("htpasswd" in call for call in host.calls)


@pytest.fixture
def real_certificate(tmp_path, monkeypatch):
    if shutil.which("openssl") is None:
        pytest.skip("OpenSSL is needed for real certificate verification")

    def openssl(*arguments):
        subprocess.run(
            ["openssl", *map(str, arguments)],
            check=True,
            capture_output=True,
            timeout=15,
        )

    root = tmp_path / "root.pem"
    root_key = tmp_path / "root.key"
    key = tmp_path / "privkey.pem"
    csr = tmp_path / "leaf.csr"
    leaf = tmp_path / "leaf.pem"
    openssl(
        "req",
        "-x509",
        "-newkey",
        "ec",
        "-pkeyopt",
        "ec_paramgen_curve:P-256",
        "-nodes",
        "-subj",
        "/CN=LocalTestCA",
        "-days",
        "10",
        "-keyout",
        root_key,
        "-out",
        root,
    )
    openssl(
        "req",
        "-new",
        "-newkey",
        "ec",
        "-pkeyopt",
        "ec_paramgen_curve:P-256",
        "-nodes",
        "-subj",
        "/CN=proxy.test",
        "-addext",
        "subjectAltName=IP:1.1.1.1",
        "-keyout",
        key,
        "-out",
        csr,
    )
    openssl(
        "x509",
        "-req",
        "-in",
        csr,
        "-CA",
        root,
        "-CAkey",
        root_key,
        "-set_serial",
        "1",
        "-days",
        "3",
        "-copy_extensions",
        "copy",
        "-out",
        leaf,
    )
    (tmp_path / "fullchain.pem").write_bytes(leaf.read_bytes() + root.read_bytes())
    monkeypatch.setattr(setup, "LINEAGE", tmp_path)
    # This private test CA trusts only locally generated fixtures; no network.
    monkeypatch.setenv("SSL_CERT_FILE", str(root))
    return SimpleNamespace(openssl=openssl, key=key, root=root)


def test_real_openssl_accepts_matching_chain_and_rejects_wrong_ip(real_certificate):
    setup.validate_certificate("1.1.1.1")
    with pytest.raises(setup.SetupError):
        setup.validate_certificate("8.8.8.8")


def test_real_openssl_rejects_an_unrelated_private_key(real_certificate):
    real_certificate.openssl(
        "genpkey",
        "-algorithm",
        "EC",
        "-pkeyopt",
        "ec_paramgen_curve:P-256",
        "-out",
        real_certificate.key,
    )
    with pytest.raises(setup.SetupError, match="do not match"):
        setup.validate_certificate("1.1.1.1")
