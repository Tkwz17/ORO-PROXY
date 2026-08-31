# Security Policy

## Reporting vulnerabilities
Please open a private security advisory or contact maintainers through GitHub Security Advisories.

## Security model notes
- OroProxy does not decrypt HTTPS traffic.
- Admin setup requires one-time first-boot setup code and mandatory password creation.
- Authentication is bound to token + client MAC.
- Quota enforcement is server-side and can revoke sessions mid-use.
