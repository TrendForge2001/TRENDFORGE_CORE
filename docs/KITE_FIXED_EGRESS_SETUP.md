# Kite fixed outbound IP setup

The owner confirmed the Kite developer account's IP whitelist is **empty** on
10 November 2026. This is a missing required configuration for API orders.
The two historical 403 PermissionException receipts do not retain the broker's
original message, so their exact individual rejection causes remain unproven.

## Provisioning handoff

Provision an operator-owned, dedicated fixed-egress host or HTTP CONNECT proxy
with one or two public addresses. Obtain the assigned addresses, authenticated
proxy connection URL and a guarantee that all failover paths use those addresses.
Preserve TLS to `api.kite.trade`; do not use a proxy that requires disabling
certificate verification or that terminates the broker TLS session.

The connected tools cannot allocate a proxy/VPS/static-IP resource or edit the
Kite developer account. No address, paid plan or whitelist entry is created by
this code. A Render compute/disk upgrade does not itself establish this route.
Do not use the website's inbound IP, an observed temporary IP or a shared CIDR.
Render's dedicated sets currently contain three possible egress IPs, while Kite
permits two whitelist entries; that combination needs a supported way to limit
the actual route before purchase.

Zerodha restricts sharing the registered IP to the owner/permitted family
accounts. Do not assume a low-cost proxy's shared static addresses qualify.
For example, QuotaGuard's current Starter/Production/Business plans explicitly
share IP pairs; dedicated addresses are separately priced. Choose a compatible
dedicated service and confirm broker/provider requirements before provisioning.

## Configure the existing Render service

In Render → trendforge-core → Environment, add these settings through the secret
UI. Never paste the authenticated proxy URL into chat, source control or logs.

| Setting | Value |
| --- | --- |
| `TRENDFORGE_KITE_PROXY_URL` | Provider's authenticated HTTP/HTTPS CONNECT proxy URL |
| `TRENDFORGE_KITE_EGRESS_IPS` | One or two provider-assigned public IPv4/IPv6 literals, comma-separated |
| `TRENDFORGE_KITE_NETWORK_PROBE_ON_START` | `true` for the read-only startup probe |
| `TRENDFORGE_LIVE_TRADING_ENABLED` | Keep `false` |
| `TRENDFORGE_OWNER_KITE_ORDER_TEST` | Keep empty |

The proxy is scoped to Kite REST requests; no global `HTTPS_PROXY` change is
needed. Invalid configuration fails closed. Proxy/network failures never retry
directly. Redirects and automatic broker HTTP retries remain disabled. Existing
market-data streaming uses its current route; its IP need not match the order
whitelist. This change does not activate a broker order workflow.

## Register the provisioned addresses

Open https://developers.kite.trade/ → Profile → IP Whitelist. Enter the exact
assigned fixed public address or addresses, maximum two, and save. Check the
values carefully: Zerodha documents one change per calendar week. This is a
developer-account setting, separate from app Redirect URL and Postback URL.

## Verify without placing a trade

After the Render environment deployment finishes, sign into
https://trendforge-core.onrender.com/app/live_kite with the existing owner/Admin
keys. Open **Kite API network and IP whitelist** and select **Check outbound IP —
no trade**. The protected API is `GET /workspace/kite-network-readiness?probe=true`.
Unauthenticated callers must not receive the network configuration.

Alternatively, in the Render service's own shell, run:

```sh
python -m scripts.check_kite_network --probe
```

The check samples three fresh HTTPS requests across two fixed IP-echo services,
using the same explicit proxy settings as Kite REST. No API keys, tokens,
account details or orders are sent to those services. Only validated IP literals
and fixed diagnostic codes are returned; proxy credentials are excluded.

Expected evidence is `observed_ips_match_configuration`, three completed samples,
and observed addresses contained in the provider-assigned set. Mismatches,
missing IPs, invalid configuration, redirects and probe failures are explicit.
Retain `orders_submitted: 0`, `broker_orders_allowed: false` and
`broker_whitelist_verified: false`. An echo check cannot prove which IP Kite
observed, the saved broker whitelist or future failover stability. Confirm the
developer-account entries and provider route guarantee separately. Authentication
and order-book reads can be verified without placing an order; neither proves
order placement permission.

## URL fields

The existing dashboard URL above is not a login callback. The screenshot's
`http://127.0.0.1` returns to the browser device and can support a manual local
token workflow. A bare `https://` postback value is incomplete. No callback or
postback endpoint is created by this networking change. Leave unimplemented
destinations unsaved; they require separate secure handlers.

## Primary references

- https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip
- https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs
- https://render.com/docs/outbound-ip-addresses
- https://render.com/docs/dedicated-ips
- https://www.quotaguard.com/products/pricing
