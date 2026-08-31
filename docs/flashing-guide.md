# Flashing Guide

1. Download `OroProxy-<board>-<version>.img.zip` from Releases.
2. Flash with Raspberry Pi Imager or `dd`.
3. Boot device with HDMI attached to read first-boot setup output.
4. Optional: remove SD card and read `oroproxy-setup-code.txt` from boot partition.
5. Connect to `OROAP`, open `http://oroproxy.local`, and complete setup wizard.
