# Architecture

OroProxy has two deliberate network modes, using the Pi's single Wi-Fi radio:

1. **Setup AP mode:** on a fresh device (or after a failed home-Wi-Fi join), `wlan0` broadcasts open `OROAP`. DNS resolves all names to the Pi and HTTP is redirected to the setup portal. The setup portal exposes only SSID/password submission over HTTP, so it works before a browser has trusted the device certificate.
2. **Home-network mode:** after a successful association and DHCP lease, hostapd, dnsmasq, and AP nftables rules are stopped and removed. Avahi advertises `oroproxy.local` on the home LAN. The forward proxy listens on TCP 3128 and the dashboard/API is served over HTTPS on TCP 8443.

The HTTP setup bridge is intentionally allow-listed to `/api/network/state` and `/api/network/connect`. It forwards those requests locally to the HTTPS API; admin authentication, user accounts, sessions, logs, quotas, and updates have no HTTP route.

If the join does not produce both an association to the requested SSID and an IPv4 lease before the timeout, the manager restores `OROAP`, DNS, and captive redirect rules. AP redirect rules are deleted before station mode, preventing captive-portal rules from affecting any home-LAN traffic.

The proxy validates each request with quota-daemon. HTTPS uses standard CONNECT tunnelling and is never decrypted.
