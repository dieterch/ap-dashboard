#!/usr/bin/env python3
import subprocess
import http.client
import json
import ipaddress
import os

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template

app = FastAPI()

MANUAL_FILE = "/etc/ap-dashboard/manual_hosts.json"

# ------------------------------------------------------------
# Manual MAC → IP registry
# ------------------------------------------------------------
def load_manual():
    try:
        with open(MANUAL_FILE) as f:
            return json.load(f)
    except:
        return {}


def save_manual(data):
    os.makedirs(os.path.dirname(MANUAL_FILE), exist_ok=True)
    with open(MANUAL_FILE, "w") as f:
        json.dump(data, f, indent=2)


def delete_manual(mac):
    data = load_manual()
    mac = mac.lower()
    if mac in data:
        del data[mac]
        save_manual(data)


@app.post("/manual/add")
def manual_add(
    mac: str = Form(...),
    ip: str = Form(...),
    name: str = Form("")
):
    data = load_manual()
    data[mac.lower()] = {
        "ip": ip.strip(),
        "name": name.strip()
    }
    save_manual(data)
    return RedirectResponse("/", status_code=302)


@app.get("/manual/delete/{mac}")
def manual_delete(mac: str):
    delete_manual(mac)
    return RedirectResponse("/", status_code=302)


# ------------------------------------------------------------
# Kick STA
# ------------------------------------------------------------
def kick_client(mac):
    subprocess.run(
        ["hostapd_cli", "-p", "/run/hostapd", "deauthenticate", mac],
        capture_output=True,
        text=True
    )


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
                parts = l.strip().split()
                if len(parts) >= 4:
                    _, mac, ip, hostname = parts[:4]
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
    manual = load_manual()
    rows = []

    for c in stas:
        mac = c["mac"].lower()
        lease = leases.get(mac, {})
        manual_entry = manual.get(mac)

        if manual_entry:
            ip = manual_entry.get("ip", "-")
            name = manual_entry.get("name") or get_shelly_name_via(ip) or "-"
            source = "manual"
        else:
            ip = lease.get("ip", "-")
            name = get_shelly_name_via(ip) or lease.get("hostname", "-")
            source = "dhcp"

        c.update({
            "ip": ip,
            "hostname": name,
            "type": "sta",
            "source": source
        })

        rows.append(c)

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
                    "type": "ext",
                    "source": "ext"
                })

    rows.sort(key=ip_sort_key)

    html = Template("""
<!DOCTYPE html>
<html>
<head>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css" rel="stylesheet">
<title>AP Dashboard</title>
</head>
<script>
setInterval(() => {
  const pause = document.getElementById("pause-refresh");
  const isPaused = pause && pause.checked;
  const hasFocus = document.querySelector(":focus");

  if (!isPaused && !hasFocus) {
    window.location.reload();
  }
}, 5000);
</script>
<body class="bg-light">
<div class="container py-4">
<h2>Access Point Dashboard</h2>
<div class="form-check form-switch mb-3">
  <input class="form-check-input" type="checkbox" id="pause-refresh">
  <label class="form-check-label" for="pause-refresh">
    Pause updates while editing
  </label>
</div>

<form class="row g-2 mb-3" method="post" action="/manual/add">
  <div class="col-md-3">
    <input class="form-control" name="mac" placeholder="MAC" required>
  </div>
  <div class="col-md-2">
    <input class="form-control" name="ip" placeholder="IP address" required>
  </div>
  <div class="col-md-3">
    <input class="form-control" name="name" placeholder="Device name">
  </div>
  <div class="col-md-2">
    <button class="btn btn-success w-100">
      <i class="bi bi-plus-circle"></i> Add
    </button>
  </div>
</form>

<table class="table table-striped table-hover align-middle">
<thead class="table-dark">
<tr>
<th>MAC</th>
<th>Access</th>
<th>Device Name</th>
<th class="text-center">Web</th>
<th class="text-center">Kick</th>
<th class="text-center">Manual</th>
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

<td class="text-center">
{% if c.source == "manual" %}
<a class="btn btn-outline-secondary btn-sm"
   href="/manual/delete/{{ c.mac }}">
<i class="bi bi-trash"></i>
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
