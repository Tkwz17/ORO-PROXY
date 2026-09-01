# Network diagram

```text
Fresh / failed join
  phone or laptop -- open Wi-Fi OROAP --> Raspberry Pi wlan0
  browser HTTP --> captive redirect --> setup portal on HTTP :80 (SSID + password only)

Successful join
  Raspberry Pi wlan0 -- Wi-Fi client --> home router --> Internet
  home-LAN clients -- mDNS oroproxy.local --> dashboard HTTPS :8443
  configured clients -- HTTP proxy oroproxy.local:3128 --> Internet
```

`hostapd`, `dnsmasq`, and AP nftables redirects run only in the upper path. The Pi removes them before using `wlan0` as a station in the lower path. Avahi remains active in both modes so `oroproxy.local` resolves to the active interface.
