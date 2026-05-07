# How It Works

This document explains what happens under the hood when you run `generate_report.py`.

---

## Overview

```
config.yaml
    │
    ▼
UnifiClient (unifi/client.py)
    │  logs in → fetches health, devices, clients, events, alarms
    ▼
build_report() (report/generator.py)
    │  processes raw API data → builds template context
    ▼
Jinja2 (templates/report.html)
    │  renders HTML
    ▼
reports/unifi_report_YYYYMMDD_HHMMSS.html
```

---

## Step 1 — Authentication

`UnifiClient.login()` sends a `POST` request to the controller's login endpoint:

| Controller type | Login endpoint |
|---|---|
| UDM / UDM-Pro | `https://{host}:443/api/auth/login` |
| Standalone Network Application | `https://{host}:8443/api/login` |

The controller responds with a session cookie (and a CSRF token for UDM). Both are stored in the `requests.Session` and sent automatically on all subsequent requests.

SSL verification is controlled by `verify_ssl` in `config.yaml`. Most self-hosted setups use a self-signed certificate, so this defaults to `false`. Set it to `true` if your controller has a valid cert.

---

## Step 2 — Data Collection

`UnifiClient.collect_report_data()` calls six API endpoints in sequence:

| Endpoint | What it returns |
|---|---|
| `/api/s/{site}/stat/health` | WAN/LAN/WLAN subsystem status, client counts |
| `/api/s/{site}/stat/device` | All UniFi devices (APs, switches, gateways) with real-time stats |
| `/api/s/{site}/stat/sta` | All currently connected clients with IP, MAC, bandwidth counters |
| `/api/s/{site}/stat/event` | Recent controller events (connections, reboots, IDS alerts, etc.) |
| `/api/s/{site}/rest/alarm` | Active unresolved alarms |
| `/api/s/{site}/stat/sysinfo` | Controller software version |

For UDM-based controllers all paths are prefixed with `/proxy/network/` — this is handled transparently by the client based on the configured port.

---

## Step 3 — Data Processing

`report/generator.py` transforms the raw API responses into structured data the template can use.

### Health
`_process_health()` pulls the `wan`, `wan2`, `lan`, and `wlan` subsystem entries out of the health list into a flat dict for easy template access.

### Devices
`_process_devices()` iterates the device list and splits it into three groups by `type` field:

- **`uap`** → Access Points — computes TX retry % from `radio_table_stats`, extracts channel info from `radio_table`
- **`usw`** → Switches — scans `port_table` for RX/TX errors and drops
- **`ugw` / `udm` / `uxg`** → Gateways — extracts WAN IP, CPU %, and memory %

### Clients
`_process_clients()` totals wireless/wired/guest counts and sorts connected clients by combined `tx_bytes + rx_bytes` to produce the top bandwidth consumers list. Byte values are converted to human-readable units (KB/MB/GB/TB).

### Events
`_process_events()` formats the most recent events for the timeline, mapping known event key strings (e.g., `EVT_AP_Restarted`, `EVT_IDS_IpsAlert`) to severity levels (`crit`, `warn`, `ok`, `info`). Timestamps are converted from UTC to the configured local timezone.

### Recommendations
`_build_recommendations()` applies threshold rules to the processed data and returns a prioritized list of findings with suggested actions:

| Check | Threshold (configurable) | Priority |
|---|---|---|
| AP TX retry rate | > 5% | Medium |
| AP uptime since last reboot | < 7 days | High |
| AP offline | Any | High |
| Switch port errors | > 100 total | Medium |
| Active alarms | Any | High |
| WAN status not `ok` | Any | High |

Thresholds are set in `config.yaml` under `report.thresholds`.

---

## Step 4 — HTML Rendering

`build_report()` loads `templates/report.html` via Jinja2's `FileSystemLoader` and calls `template.render(**ctx)`. The template uses Jinja2's auto-escaping to prevent XSS from any controller-provided strings (device names, hostnames, etc.).

The rendered HTML is a single self-contained file — no external CSS frameworks, no JavaScript, no CDN dependencies. It will render correctly offline and can be emailed as an attachment.

---

## Step 5 — Output

The report is written to:

```
{output_dir}/unifi_report_{YYYYMMDD}_{HHMMSS}.html
```

The `reports/` directory is gitignored so generated files are never committed. Pass `--open` to the CLI to have the report open in your default browser immediately after generation.

---

## API Compatibility Notes

- The UniFi Network API is unofficial and undocumented by Ubiquiti. Field names and response shapes can change between controller versions.
- The client has been written against **UniFi Network Application 7.x** and **UDM firmware 3.x+**.
- If a field is missing from a response, the code defaults gracefully (empty list, `"—"`, or `0`) rather than raising an exception.
- The `dpi` endpoint is fetched optionally — it is silently skipped if unavailable (some controller configurations disable it).
