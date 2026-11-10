# Dedicated Ubuntu HTTPS proxy installation

This installs only the network gateway on the dedicated Ubuntu 24.04 VM. It
does not install a second Trendforge executor, alter Render credentials or
submit a broker order. Trendforge continues running on Render.

## Prerequisites

- A dedicated attached static public IPv4, confirmed against an IPv4 IP echo.
- Ubuntu 24.04 with `squid-openssl`, `apache2-utils`, `openssl` and CA certificates.
- A publicly trusted Certbot certificate covering that IPv4, named
  `trendforge-kite-proxy`, under `/etc/letsencrypt/live/trendforge-kite-proxy`.
- The Snap Certbot renewal timer must be active. HTTP port 80 must remain
  available for future standalone certificate validation.
- Keep the proxy port closed in the Lightsail firewall until configuration
  succeeds. Preserve the existing SSH access rule.

## Run the verified installer

Download `scripts/configure_kite_proxy.py` from the exact Git commit supplied in
the installation handoff. Compare its SHA-256 before running it with sudo.
This version's SHA-256 is:

`94f70f657e9fa917c42ad9ae23523140a9f3b2877cc429ff50690aff3d319884`

Run `sudo python3 /tmp/configure_kite_proxy.py --configure YOUR_STATIC_IPV4`,
substituting the actual dedicated IPv4. Use the copy button for each complete
command; do not split a command into separate option lines.

The installer checks the OS, OpenSSL-enabled Squid, authentication helper,
renewal timer, certificate IP, trust chain, validity and matching private key.
It backs up `/etc/squid/squid.conf` before replacing it. Existing installations
or credential files are refused to prevent accidental password rotation.

The service listens on IPv4 HTTPS port 8443, requires a generated password,
permits CONNECT only to port 443 for `api.kite.trade`, `api4.ipify.org` and
`checkip.amazonaws.com`, and rejects private/link-local destinations. The
service's address-family restriction prevents IPv6 egress. It does not decrypt
the TLS tunnel to Kite. No plaintext proxy listener is configured.

The password is generated on the VM, passed privately to the hashing helper,
and saved in `/root/trendforge-kite-proxy.env` with mode 0600. It is not printed.
Squid's key and password hash are readable only by root and the proxy group.
The script validates Squid's configuration before starting the service; a
configuration failure leaves it stopped. Inspect failures locally before retrying.

## Test renewal and restrict the cloud firewall

Run the following as a single line on the VM:

`sudo /snap/bin/certbot renew --cert-name trendforge-kite-proxy --dry-run --run-deploy-hooks`

Certbot's deploy hook runs the installed helper only for this certificate's
lineage. The helper validates and copies the renewed certificate/key, parses
Squid's configuration and reloads the service. Validation failures do not
replace installed certificates; parse/reload failures restore previous files.

After configuration and renewal checks succeed, add an IPv4 inbound TCP 8443
rule limited to the Render service's published outbound CIDRs, obtained from
Render → trendforge-core → Connect → Outbound. Add a rule for each required
range. Keep HTTP 80 accessible for ACME and preserve SSH. No IPv6 proxy rule is
needed. Do not enable an unrestricted unauthenticated HTTP proxy.

## Configure Render privately

On the VM, use `sudo cat /root/trendforge-kite-proxy.env` to view the generated
settings in your private terminal. Copy the values into Render's Environment
settings, or use its Add from .env editor. Never paste this file or a screenshot
of it into chat or GitHub: it contains the authenticated proxy URL.

The generated values keep `TRENDFORGE_LIVE_TRADING_ENABLED=false` and the
one-shot owner-order intent empty. Save and deploy the Render service.

Use Live Kite Session → Kite API network and IP whitelist → Check outbound IP —
no trade. Confirm the observed address matches the assigned static IPv4 before
saving the numeric address under Kite Developer Console → Profile → IP Whitelist.
An IP echo cannot itself verify the saved broker whitelist or order permission.

## Evidence and limits

Tests cover credential permissions/privacy, prerequisite admission, refusal to
overwrite credentials, validation before service start, certificate rollback,
real OpenSSL trust/IP/key checks and the restricted configuration. Actual Squid
parsing, service activation, certificate renewal and external reachability must
pass on the dedicated host. No test or installer submits a broker order.

References:
- https://letsencrypt.org/2026/03/11/shorter-certs-certbot.html
- https://www.squid-cache.org/Doc/config/https_port/
- https://www.squid-cache.org/Doc/config/acl/
- https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-editing-firewall-rules.html
