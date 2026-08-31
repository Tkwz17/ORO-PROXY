# Architecture

OroProxy is split into system services:
- **ap-manager** configures hostapd, dnsmasq, and nftables captive flow.
- **portal-web** serves the login and admin UI quickly without a frontend build chain.
- **portal-api** handles users, admin auth, sessions, and dashboard APIs on HTTPS.
- **quota-daemon** tracks active authenticated session time and revokes exhausted MACs.
- **proxy** forwards HTTP and HTTPS CONNECT traffic for authenticated sessions.

Flow:
1. Client joins open `OROAP`.
2. nftables redirects unauthenticated client traffic to portal.
3. Login creates authenticated session (token + MAC binding).
4. portal-api starts quota-daemon session and ap-manager adds MAC to nft set.
5. proxy validates session and quota on each request.
6. quota-daemon removes MAC from authenticated set when quota is exhausted.
