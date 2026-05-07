# UniFi Network Health Report &nbsp; ![version](https://img.shields.io/badge/version-1.0.0-blue) ![license](https://img.shields.io/badge/license-Apache%202.0-green)

A Python tool that connects to a self-hosted **Ubiquiti UniFi Network Application** and generates a clean, standalone HTML report covering network health, client activity, access point performance, switch status, recent events, and actionable recommendations.

---

## Features

- **WAN / Gateway status** — online/offline, WAN IP, CPU and memory usage
- **Client summary** — total connected clients, wireless vs. wired vs. guest breakdown, top bandwidth consumers
- **Access point health** — per-AP client count, TX retry rate, channel info, uptime, firmware version, and auto-generated status badges
- **Switch overview** — port count, port-level error detection
- **Event timeline** — most recent controller events with severity indicators
- **Recommendations** — automatically flagged issues (high retry rates, recent reboots, offline devices, active alarms, port errors)
- **On-demand generation** — run it when you need it; output is a single self-contained HTML file

---

## Requirements

- Python 3.9+
- A self-hosted UniFi Network Application (UDM, UDM-Pro, or standalone Network Application)
- An admin account on the controller

---

## Installation

```bash
git clone https://github.com/yourname/Unifi_Network_Health_Report.git
cd Unifi_Network_Health_Report

pip install -r requirements.txt
```

---

## Configuration

Copy the example config and fill in your details:

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`:

```yaml
unifi:
  host: "192.168.1.1"       # your controller IP or hostname
  port: 443                  # 443 for UDM/UDM-Pro, 8443 for standalone app
  username: "admin"
  password: "your-password"
  site: "default"
  verify_ssl: false          # true if you have a valid TLS cert

report:
  site_name: "My Network"
  output_dir: "reports"
  timezone: "America/Chicago"
  thresholds:
    ap_retry_pct: 5.0
    ap_reboot_days: 7
    switch_error_rate: 100
```

`config.yaml` is listed in `.gitignore` — your credentials will never be committed.

---

## Usage

```bash
# Generate report (saved to reports/ directory)
python generate_report.py

# Generate and open in your browser immediately
python generate_report.py --open

# Use a different config file
python generate_report.py --config /path/to/other.yaml

# Enable verbose debug output
python generate_report.py --debug
```

The report is saved as a timestamped HTML file in the `reports/` directory, e.g.:

```
reports/unifi_report_20250505_060000.html
```

---

## Project Structure

```
Unifi_Network_Health_Report/
├── generate_report.py       # CLI entry point
├── config.example.yaml      # config template (safe to commit)
├── config.yaml              # your config with credentials (gitignored)
├── requirements.txt
├── unifi/
│   └── client.py            # UniFi API client
├── report/
│   └── generator.py         # data processing and HTML rendering
├── templates/
│   └── report.html          # Jinja2 HTML template
└── reports/                 # generated reports output (gitignored)
```

---

## Supported Controllers

| Controller | Default Port | Notes |
|---|---|---|
| UDM / UDM-Pro / UDM-SE | 443 | Uses `/proxy/network/` API prefix |
| UDM-Pro Max | 443 | Same as UDM-Pro |
| UniFi Network Application (self-hosted) | 8443 | Direct API, no prefix |

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
