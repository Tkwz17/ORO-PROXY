# Network Diagram

```text
[Client Devices]
      |
   Wi-Fi SSID: OROAP (open)
      |
[hostapd + dnsmasq]
      |
[nftables captive policy]
   | unauthenticated -> portal-web / portal-api
   | authenticated   -> proxy
      |
[proxy service]
      |
[Internet uplink]

Control plane:
portal-api <-> quota-daemon <-> nftables authenticated MAC set
```
