# Flashing Guide

1. Download `OroProxy-<board>-<version>.img.zip` from Releases.
2. Flash with Raspberry Pi Imager or `dd`.
3. Boot device with HDMI attached to read first-boot setup output.
4. Optional: remove SD card and read `oroproxy-setup-code.txt` from boot partition.
5. Connect to `OROAP` and open `http://oroproxy.local`. This setup page only asks for the home Wi-Fi SSID and password.
6. After a successful join, reconnect your device to the same home Wi-Fi. Configure the forward proxy as `oroproxy.local:3128`; use `https://oroproxy.local:8443` for the dashboard. If joining fails, reconnect to `OROAP` and correct the credentials.
