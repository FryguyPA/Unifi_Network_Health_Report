# UniFi Network Health Report &nbsp; ![version](https://img.shields.io/badge/version-1.3.0-blue) ![license](https://img.shields.io/badge/license-Apache%202.0-green)

A Python tool that connects to a self-hosted **Ubiquiti UniFi Network Application** and generates a clean, standalone HTML report covering network health, traffic analysis, device status, security policy, and actionable recommendations.

👉 **[View example report](docs/unifi_report_demo.html)** — generated from realistic dummy data via `generate_demo_report.py`

---

## Features

- **Recommendations first** — auto-generated, prioritized action items surface at the top of every report
- **WAN / Gateway status** — per-connection IP, ISP, media type, availability %, latency, and uptime; dual-WAN supported
- **WAN utilization chart** — 24-hour inline SVG area chart of TX/RX throughput (Mbps)
- **Traffic Analysis** — 24 h per-client bandwidth via `stat/report`; device-category breakdown (Computers, Phones, IoT, Media, Gaming); hourly activity pattern chart
- **Top bandwidth consumers** — current-session clients ranked by bytes with network/VLAN badge
- **Client Inventory** — all known devices (connected + historical) with MAC fingerprinting, device type, OUI, last-seen timestamp; sortable table
- **Access point health** — per-AP client count, TX retry %, channel, uptime, and status badge
- **Switch overview** — port count, PoE budget bar (used/total watts), per-port error dropdowns
- **Firmware compliance** — every device with version and upgrade availability
- **Wireless Networks** — SSID table with security mode, bands, and guest flag; client counts by type
- **VPN** — remote-user session count, site-to-site toggle, session traffic totals
- **Networks & VLANs** — all configured networks with type, VLAN ID, subnet, and DHCP status
- **Zone Firewall Policies** *(requires API key)* — v1 API zone-based policies with source/dest zone, action, and traffic filter summary
- **DNS & Content Filtering** *(requires API key)* — v1 API DNS policies
- **Legacy Firewall Rules** — per-ruleset rule tables with security flag detection; firewall groups; traffic routes; port-forwarding rules
- **Event timeline** — recent controller events with severity indicators
- **Four themes** — Light, Dark Terminal, Slate & Amber, Deep Navy; preference saved in `localStorage`
- **Collapsible sections** — click any section heading to collapse/expand; state persists across reloads
- **JSON snapshots** — every run writes a structured `reports/json/unifi_snapshot_<timestamp>.json` for historical comparison

---

## Requirements

- Python 3.9+
- A self-hosted UniFi Network Application (UDM, UDM-Pro, UDM-SE, or standalone Network Application)
- An admin account on the controller
- *(Optional)* A v1 API key for Zone Firewall and DNS Policy sections

---

## Installation

```bash
git clone https://github.com/yourname/Unifi_Network_Health_Report.git
cd Unifi_Network_Health_Report
pip install -r requirements.txt
```

---

## Configuration

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`:

```yaml
unifi:
  host: "192.168.1.1"       # controller IP or hostname
  port: 443                  # 443 for UDM/UDM-Pro, 8443 for standalone
  username: "admin"
  password: "your-password"
  verify_ssl: false          # true if you have a valid TLS cert

  # Optional — enables Zone Firewall Policies and DNS Policies sections.
  # Generate in: UniFi Network → Settings → System → Advanced → API Keys
  # api_key: "your-api-key-here"

report:
  site_name: "My Network"
  output_dir: "reports"
  timezone: "America/Chicago"
  thresholds:
    ap_retry_pct: 5.0        # AP TX retry % above this is flagged
    ap_reboot_days: 7        # AP rebooted within N days is flagged
    switch_error_rate: 100   # switch port error count above this is flagged
```

`config.yaml` is listed in `.gitignore` — credentials are never committed.

---

## Usage

```bash
# Generate report (saved to reports/)
python generate_report.py

# Generate and open in browser immediately
python generate_report.py --open

# Use a different config file
python generate_report.py --config /path/to/other.yaml

# Enable verbose debug output
python generate_report.py --debug
```

Each run produces two output files with matching timestamps:

```
reports/
  unifi_report_20260511_120000.html      ← the visual report
  json/
    unifi_snapshot_20260511_120000.json  ← structured data snapshot for comparison
```

---

## Project Structure

```
Unifi_Network_Health_Report/
├── generate_report.py        # CLI entry point
├── config.example.yaml       # config template (safe to commit)
├── config.yaml               # your config with credentials (gitignored)
├── requirements.txt
├── unifi/
│   └── client.py             # UniFi API client (cookie auth + v1 API key auth)
├── report/
│   └── generator.py          # data processing, SVG charts, HTML + JSON rendering
├── templates/
│   └── report.html           # Jinja2 template — self-contained, no CDN dependencies
└── reports/                  # generated output (gitignored)
    ├── unifi_report_*.html
    └── json/
        └── unifi_snapshot_*.json
```

---

## Supported Controllers

| Controller | Default Port | Notes |
|---|---|---|
| UDM / UDM-Pro / UDM-SE | 443 | Uses `/proxy/network/` API prefix |
| UDM-Pro Max | 443 | Same as UDM-Pro |
| UniFi Network Application (self-hosted) | 8443 | Direct API, no prefix |

v1 API endpoints (Zone Firewall, DNS Policies) require **Network Application 10.1+** and an API key generated in the controller UI.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
