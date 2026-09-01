# OroProxy

OroProxy turns a Raspberry Pi into a portable Wi-Fi setup access point that joins a home network and then provides an authenticated web proxy with admin-managed daily user time quotas on that home network.

## Highlights
- Open setup SSID `OROAP` on first boot or after a failed join
- Setup page at `http://oroproxy.local` accepts only the home Wi-Fi SSID and password
- After joining, Avahi advertises `oroproxy.local` and the proxy listens on TCP `3128` on the home network
- Per-user daily minute quotas enforced server-side
- HTTPS admin dashboard with per-device self-signed cert generation
- First-run setup code flow (no baked default admin password)
- Manual check/apply update flow via dashboard and update scripts
- Pi image builds for Pi 3, Pi 4, and Pi 5 via GitHub Actions + pi-gen

## Repository layout
- `image-build/`: pi-gen configs and custom stage
- `services/ap-manager`: hostapd, dnsmasq, nftables templates and auth-set script
- `services/proxy`: Go forward proxy with CONNECT tunneling
- `services/portal-api`: FastAPI backend for auth, admin, users, and sessions
- `services/portal-web`: no-build static login/admin UI
- `services/quota-daemon`: Go daemon for quota/session enforcement
- `systemd/`: service and timer units
- `scripts/`: first-boot setup and update checker
- `tests/`: project tests

## Development quickstart
### Proxy
```bash
cd services/proxy
go test ./...
```

### Quota daemon
```bash
cd services/quota-daemon
go test ./...
```

### Portal API
```bash
cd services/portal-api
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

## Security and privacy defaults
- HTTPS tunneling only for CONNECT; no TLS MITM or decryption.
- Captive sessions bind token + MAC address.
- Destination hostname logging is configurable and clearly labeled due to privacy tradeoffs.
- If quota/auth services are unavailable, new sessions fail closed while recently validated sessions get a brief grace window.

## License
MIT (see `LICENSE`).
