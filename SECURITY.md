# Reporting a vulnerability

Contact the repository owner privately through the security contact on their GitHub profile or use GitHub private vulnerability reporting when available. Include the affected revision and the security impact. Keep credentials, broker tokens, portfolio data, and vulnerability details out of public issues.

## Production access

Only the owner or an explicitly authorized administrator holding the admin API key may operate the paper kill switch. Keep that key separate from owner sign-in, scheduler, and feed credentials.

Configure TRENDFORGE_WEBAPP_ACCESS_KEY and TRENDFORGE_OWNER_SIGNING_SECRET with independently generated random secrets of at least 32 characters. Rotating either invalidates active owner sessions. The PC launcher creates separate private credential files automatically. Local development can explicitly set TRENDFORGE_DEV_DISABLE_API_AUTH=1 on a loopback-only development server.

The owner portal logs a warning when a client reaches 20 failed attempts within five minutes. Monitor this warning in production logs. If deploying behind a reverse proxy, configure Uvicorn's FORWARDED_ALLOW_IPS with the actual trusted proxy addresses and have that proxy overwrite incoming forwarding headers.
