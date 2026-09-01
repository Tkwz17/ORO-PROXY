# Admin Guide

## First-run setup
- On first boot OroProxy writes a random setup code to:
  - Console output (HDMI)
  - `/boot/oroproxy-setup-code.txt`
- Use this code once to set the admin password.

## Dashboard capabilities
- Manage users and daily minute quotas
- View active sessions and remaining time
- Revoke sessions manually
- Enable/disable destination-host logging (privacy-sensitive)
- View and clear basic connection event logs
- Change admin password and inspect device health
- Check for updates and apply release updates manually

## HTTPS trust
The device generates a unique self-signed certificate at first boot in `/etc/oroproxy/tls/`. Import this cert into trusted stores on admin devices to remove warnings.

## Updates
- Background checks run via `oroproxy-update-check.timer`.
- Manual update application runs `/opt/oroproxy/scripts/apply-update.sh`, which downloads the latest tagged release and restarts OroProxy services.
