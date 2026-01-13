#!/usr/bin/env python3
import subprocess
import http.client
import json
import ipaddress

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template

app = FastAPI()

# ------------------------------------------------------------
# Kick STA
# ------------------------------------------------------------
def kick_client(mac):
    try:
        subprocess.run(
            ["hostapd_cli", "-p", "/run/hostapd", "deauthenticate", mac],
            capture_output=True,
            text=True
        )
        return True
    except:
        return False


@app.get("/kick/{mac}")
def kick_endpoint(mac: str):
    kick_client(mac)
    return RedirectResponse("/", status_code=302)


# ------------------------------------------------------------
# Shelly Name Resolution
# ------------------------------------------------------------
def get_shelly_name(ip):
    if not ip or ip == "-" or ip is None:
        return None

    # Gen2 / Plus RPC
    try:
        conn = http.client.HTTPConnection(ip, timeout=0.5)
        conn.request("GET", "/rpc/Shelly.GetDeviceInfo")
        res = conn.getresponse()
        if res.status == 200:
            data = json.loads(res.read().decode())
            return data.get("name") or data.get("id")
    except:
        pass

    # Gen1 /settings
    try:
        conn = http.client.HTTPConnection(ip, timeout=0.5)
        conn.request("GET", "/settings")
        res = conn.getresponse()
        if res.status == 200:
            data = json.loads(res.read().decode())

            if data.get("name"):
                return data["name"]

            dev = data.get("device", {})
            if dev.get("hostname"):
                return dev["hostname"]

            if dev.get("type") and dev.get("mac"):
                return f"{dev['type']}-{dev['mac'][-6:]}"
    except:
        pass

    return None


# ------------------------------------------------------------
# hostapd
# ------------------------------------------------------------
def get_sta():
    result = subprocess.run(
        ["hostapd_cli", "-p", "/run/hostapd", "list_sta"],
        capture_output=True,
        text=True
    ).stdout

    macs = [line.strip() for line in result.splitlines() if ":" in line]
    clients = []

    for mac in macs:
        sta = {"mac": mac}

        detail = subprocess.run(
            ["hostapd_cli", "-p", "/run/hostapd", "sta", mac],
            capture_output=True,
            text=True
        ).stdout

        for line in detail.splitlines():
            if "=" in line:
                k, v = line.strip().split("=", 1)
                sta[k] = v

        clients.append(sta)

    return clients


# ------------------------------------------------------------
# dnsmasq leases
# ------------------------------------------------------------
def get_leases():
    leases = {}
    try:
        with open("/var/lib/misc/dnsmasq.leases") as f:
            for l in f:
                _, mac, ip, hostname, _ = l.strip().split(" ")
                leases[mac.lower()] = {
                    "ip": ip,
                    "hostname": hostname if hostname else "-"
                }
    except:
        pass
    return leases


# ------------------------------------------------------------
# Helper: IP sort key
# ------------------------------------------------------------
def ip_sort_key(client):
    ip = client.get("ip")
    try:
        return (0, ipaddress.IPv4Address(ip))
    except:
        # Geräte ohne IP ans Ende
        return (1, None)


# ------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard():
    stas = get_sta()
    leases = get_leases()

    for c in stas:
        mac = c["mac"].lower()
        lease = leases.get(mac, {})

        ip = lease.get("ip", "-")
        hostname = lease.get("hostname", "-")

        shelly_name = get_shelly_name(ip)
        final_name = shelly_name or hostname or "Unknown"

        c["ip"] = ip
        c["hostname"] = final_name

    # 🔽 SORTIERUNG NACH IP
    stas.sort(key=ip_sort_key)

    html = Template("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="5"/>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css" rel="stylesheet">
        <title>AP Dashboard</title>
    </head>
    <body class="bg-light">

        <div class="container py-4">
            <h2 class="mb-3">Access Point Dashboard</h2>
            <p class="text-muted">Automatische Aktualisierung alle 5 Sekunden</p>

            <table class="table table-striped table-hover align-middle">
                <thead class="table-dark">
                    <tr>
                        <th>MAC</th>
                        <th>IP</th>
                        <th>Device Name</th>
                        <th class="text-center">Web</th>
                        <th class="text-center">Kick</th>
                        <th>Signal (dBm)</th>
                        <th>RX</th>
                        <th>TX</th>
                        <th>Uptime (s)</th>
                    </tr>
                </thead>
                <tbody>
                    {% for c in clients %}
                    <tr>
                        <td>{{ c.mac }}</td>
                        <td>{{ c.ip }}</td>
                        <td>{{ c.hostname }}</td>

                        <td class="text-center">
                            {% if c.ip != "-" %}
                                <a class="btn btn-outline-primary btn-sm"
                                   href="http://{{ c.ip }}"
                                   target="_blank"
                                   title="Open Web UI">
                                    <i class="bi bi-box-arrow-up-right"></i>
                                </a>
                            {% else %}
                                -
                            {% endif %}
                        </td>

                        <td class="text-center">
                            <a class="btn btn-outline-danger btn-sm"
                               href="/kick/{{ c.mac }}"
                               title="Kick device">
                               <i class="bi bi-x-circle"></i>
                            </a>
                        </td>

                        <td>{{ c.signal }}</td>
                        <td>{{ c.rx_bytes }}</td>
                        <td>{{ c.tx_bytes }}</td>
                        <td>{{ c.connected_time }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

    </body>
    </html>
    """)

    return html.render(clients=stas)
