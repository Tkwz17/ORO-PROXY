# Contributing

## Setup
1. Install Go 1.22+ and Python 3.11+.
2. Run service tests before opening a PR.

## Pull requests
- Keep changes scoped and documented.
- Include tests for behavior changes.
- Respect privacy defaults and security model (no TLS MITM).

## Validation
- `go test ./...` under `services/proxy` and `services/quota-daemon`
- `pytest` under `services/portal-api`
