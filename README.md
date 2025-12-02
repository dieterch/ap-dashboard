## ✅ Debian 13 WLAN Access Point unter Proxmox

🧱 1. Voraussetzungen
**Hardware**
* Proxmox Host
* USB-WLAN-Adapter (z. B. Realtek RTL88x2BU oder ähnlich)
* Debian 13 VM (minimal)

**Proxmox Konfiguration**
Im VM-Hardware Tab:
1. USB-Gerät zuordnen
    * Add → USB Device → deinen WLAN-Stick auswählen
2. Netzwerkkarte für Internet
    * „VM NIC“ → Bridge: vmbr0
Keine weiteren NATs im Proxmox nötig — NAT macht Debian.

# 📦 2. Debian 13 vorbereiten
**Update**
```
sudo apt update
sudo apt upgrade -y
sudo apt install -y hostapd dnsmasq nftables iw tcpdump git python3-venv python3-pip
```

# 🌐 3. WLAN-Interface prüfen

```
ip link
```

Typischer Name: **wlxE0D362FC6DF0**
Wenn dein Name anders ist → anpassen!

# 🧩 4. systemd-networkd verwenden
Debian 13 nutzt systemd-networkd statt /etc/network/interfaces.
Datei erstellen:

```
/etc/systemd/network/12-wlan-ap.network

[Match]
Name=wlxE0D362FC6DF0

[Network]
Address=192.168.5.1/24

ConfigureWithoutCarrier=yes
```
**Aktivieren:**
```
sudo systemctl enable --now systemd-networkd
```

# 🎛 5. Hostapd konfigurieren (WLAN AP)

Datei erstellen:

```
/etc/hostapd/hostapd.conf

country_code=AT
interface=wlxe0d362fc6df0
driver=nl80211
ssid=CHVHA2
hw_mode=g
channel=6
wpa=2
wpa_passphrase=DEINPASSWORT
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
ctrl_interface=/run/hostapd
```

Hostapd aktivieren:
```
sudo systemctl enable --now hostapd
```

Check:
```
systemctl status hostapd
```

# 💡 6. dnsmasq konfigurieren (DHCP & DNS)

Datei:
```
/etc/dnsmasq.d/ap.conf

interface=wlxe0d362fc6df0
dhcp-range=192.168.5.2,192.168.5.50,24h
dhcp-authoritative
dhcp-option=6,1.1.1.1
```

➡️ DNS per 1.1.1.1 — funktioniert sicher.(Alternativ: dein lokales BIND 192.168.15.122)

dnsmasq neu starten:
```
sudo systemctl restart dnsmasq
```

Prüfen:
```
systemctl status dnsmasq
```

# 🌍 7. NAT & Routing aktivieren
IP-Forwarding einschalten
```
echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward
```
Permanent machen:
```
sudo sh -c "echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-ipforward.conf"
```

nftables Regel:
```
/etc/nftables.conf

table ip nat {
  chain postrouting {
      type nat hook postrouting priority srcnat; policy accept;
      oif "ens18" ip saddr 192.168.5.0/24 masquerade
  }
}
```

Aktivieren:
```
sudo systemctl enable --now nftables
sudo systemctl restart nftables
```

Check:
```
nft list ruleset
```

# 📶 8. Testen deiner Konfiguration
Auf einem Client (iPhone/iPad/Shelly):
1. WLAN: CHVHA2
2. IP sollte im Bereich 192.168.5.2–50 liegen
3. Gateway: 192.168.5.1
4. DNS: 1.1.1.1

Test:
```
ping 8.8.8.8
ping google.com
```

Wenn 8.8.8.8 geht, aber google.com nicht → DNS prüfen.

# 📊 9. Dashboard installieren (Optional, aber sehr geil)

Ordner anlegen:
```
sudo mkdir -p /opt/ap-dashboard
cd /opt/ap-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Dashboard Datei:/opt/ap-dashboard/dashboard.py

```
Systemd Service:/etc/systemd/system/ap-dashboard.service

[Unit]
Description=Access Point Dashboard
After=network.target

[Service]
ExecStart=/opt/ap-dashboard/venv/bin/uvicorn dashboard:app --host 0.0.0.0 --port 8080
WorkingDirectory=/opt/ap-dashboard
Restart=always
User=root

[Install]
WantedBy=multi-user.target
Starten & aktivieren:

sudo systemctl daemon-reload
sudo systemctl enable --now ap-dashboard
```

Dashboard öffnen:

http://192.168.5.1:8080

# 🚀 10. Shelly Optimierung
**Für Shelly Gen1/Gen2 Geräte:**
* 2.4 GHz verwenden
* HT40 vermeiden → du nutzt korrekt g (20 MHz)
* Channel 1 / 6 / 11 nutzen → du nutzt 6
* DHCP muss schnell antworten → dnsmasq tut das
* Private WLAN Addressing auf iOS aus → erledigt

# 🧹 11. Kontrolle bei Fehlern
**Hostapd:**
```
journalctl -u hostapd -f
```

**dnsmasq:**
```
journalctl -u dnsmasq -f
```

**DHCP sniffen:**
```
tcpdump -i wlxe0d362fc6df0 port 67 or port 68 -nn
```

# 🎉 12. Fertig!
Du hast jetzt:
* ✔ AP auf Debian 13 VM
* ✔ DHCP
* ✔ NAT
* ✔ saubere networkd config
* ✔ Hostapd
* ✔ DNS
* ✔ Shellies funktionieren
* ✔ Dashboard mit Kick-Button & Web-Links
