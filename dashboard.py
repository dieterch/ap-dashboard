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
# Shelly RPC helper
# ------------------------------------------------------------
def shelly_rpc(host, path):
    try:
        conn = http.client.HTTPConnection(host, timeout=0.7)
        conn.request("GET", path)
        res = conn.getresponse()
        if res.status == 200:
            return json.loads(res.read().decode())
    except:
        pass
    return None


def get_shelly_name_via(host):
    data = shelly_rpc(host, "/rpc/Shelly.GetDeviceInfo")
    if data:
        return data.get("name") or data.get("id")
    return None


def is_range_extender(ip):
    data = shelly_rpc(ip, "/rpc/WiFi.GetConfig")
    if not data:
        return False
    return data.get("ap", {}).get("range_extender", {}).get("enable", False)


def get_extender_clients(ip):
    data = shelly_rpc(ip, "/rpc/WiFi.ListAPClients")
    if not data:
        return []
    return data.get("ap_clients", [])


# ------------------------------------------------------------
# hostapd
# ------------------------------------------------------------
def get_sta():
    result = subprocess.run(
        ["hostapd_cli", "-p", "/run/hostapd", "list_sta"],
        capture_output=True,
        text=True
    ).stdout

    macs = [l.strip() for l in result.splitlines() if ":" in l]
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
                k, v = line.split("=", 1)
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
                leases[mac.lower()] = {"ip": ip, "hostname": hostname}
    except:
        pass
    return leases


def ip_sort_key(c):
    try:
        return (0, ipaddress.IPv4Address(c["ip"].split(":")[0]))
    except:
        return (1, None)


# ------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard():
    stas = get_sta()
    leases = get_leases()
    rows = []

    for c in stas:
        mac = c["mac"].lower()
        lease = leases.get(mac, {})
        ip = lease.get("ip", "-")

        name = get_shelly_name_via(ip) or lease.get("hostname", "-")

        c.update({
            "ip": ip,
            "hostname": name,
            "type": "sta"
        })

        rows.append(c)

        # ----- Extender clients -----
        if ip != "-" and is_range_extender(ip):
            for cl in get_extender_clients(ip):
                host = f"{ip}:{cl['mport']}"
                cname = get_shelly_name_via(host) or "Shelly Client"

                rows.append({
                    "mac": cl["mac"],
                    "ip": host,
                    "hostname": f"↳ {cname}",
                    "signal": "",
                    "rx_bytes": "",
                    "tx_bytes": "",
                    "connected_time": cl["since"],
                    "type": "ext"
                })

    rows.sort(key=ip_sort_key)

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
<h2>Access Point Dashboard</h2>

<table class="table table-striped table-hover align-middle">
<thead class="table-dark">
<tr>
<th>MAC</th>
<th>Access</th>
<th>Device Name</th>
<th class="text-center">Web</th>
<th class="text-center">Kick</th>
<th>Signal</th>
<th>RX</th>
<th>TX</th>
<th>Uptime</th>
</tr>
</thead>
<tbody>
{% for c in clients %}
<tr class="{% if c.type == 'ext' %}table-secondary{% endif %}">
<td>{{ c.mac }}</td>
<td>{{ c.ip }}</td>
<td>{{ c.hostname }}</td>

<td class="text-center">
<a class="btn btn-outline-primary btn-sm"
   href="http://{{ c.ip }}" target="_blank">
<i class="bi bi-box-arrow-up-right"></i>
</a>
</td>

<td class="text-center">
{% if c.type == 'sta' %}
<a class="btn btn-outline-danger btn-sm" href="/kick/{{ c.mac }}">
<i class="bi bi-x-circle"></i>
</a>
{% endif %}
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

    return html.render(clients=rows)
