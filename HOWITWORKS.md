# How It Works

This document explains what happens under the hood when you run `generate_report.py`.

---

## Overview

```
config.yaml
    │
    ▼
UnifiClient (unifi/client.py)
    │  cookie-auth login → fetches all API endpoints
    │  v1 API key → fetches zone firewall + DNS policies
    ▼
build_report() (report/generator.py)
    │  processes raw API data → builds template context + SVG chart data
    ▼
Jinja2 (templates/report.html)         _build_snapshot()
    │  renders HTML report                   │
    ▼                                        ▼
reports/unifi_report_YYYYMMDD_HHMMSS.html   reports/json/unifi_snapshot_*.json
```

---

## Step 1 — Authentication

`UnifiClient.login()` sends a `POST` to the controller's login endpoint:

| Controller type | Login endpoint |
|---|---|
| UDM / UDM-Pro | `https://{host}:443/api/auth/login` |
| Standalone Network Application | `https://{host}:8443/api/login` |

The controller responds with a session cookie (and a CSRF token for UDM). Both are stored in a `requests.Session` and sent automatically on all subsequent legacy API requests.

If `api_key` is set in `config.yaml`, a separate `requests.Session` is created with an `X-API-Key` header for the v1 integration API. The two sessions are completely independent — the v1 session never needs login cookies.

---

## Step 2 — Site Discovery

After login, `prompt_for_site()` calls `GET /api/self/sites` to list all sites the account can access. If only one site exists it is auto-selected; otherwise an interactive numbered menu is shown.

For v1 API calls, `_resolve_v1_site()` calls `GET /integration/v1/sites` to retrieve the site's UUID (`id` field), which differs from the site slug used by the legacy API.

---

## Step 3 — Data Collection

`UnifiClient.collect_report_data()` fetches all endpoints in parallel (each wrapped in `_safe()` so a failed endpoint logs a warning and returns an empty result rather than aborting):

### Legacy API (cookie session)

| Endpoint | What it returns |
|---|---|
| `/api/s/{site}/stat/health` | WAN/LAN/WLAN subsystem status, client counts, speedtest |
| `/api/s/{site}/stat/device` | All UniFi devices (APs, switches, gateways) with real-time stats |
| `/api/s/{site}/stat/sta` | Currently connected clients with IP, MAC, and bandwidth counters |
| `/api/s/{site}/rest/user` | All known clients including disconnected, with device fingerprinting |
| `/api/s/{site}/stat/sysinfo` | Controller software version and hostname |
| `/api/s/{site}/rest/wlanconf` | Configured SSIDs and wireless settings |
| `/api/s/{site}/rest/networkconf` | All networks (VLANs, WAN, VPN) |
| `/api/s/{site}/rest/firewallrule` | Legacy user-defined firewall rules |
| `/api/s/{site}/rest/firewallgroup` | Firewall address/port groups |
| `/api/s/{site}/rest/alarm` | Active unresolved alarms |
| `/api/s/{site}/rest/portforward` | Port-forwarding / DNAT rules |
| `/v2/api/site/{site}/trafficroutes` | Policy routing / WAN-selection rules |
| `/api/s/{site}/stat/report/hourly.site` | WAN TX/RX bytes per hour (last 24 h) |
| `/api/s/{site}/stat/report/daily.user` | Per-client TX/RX bytes (last 24 h) |
| `/api/s/{site}/stat/report/hourly.user` | Per-client TX/RX bytes per hour (last 24 h) |
| `/v2/api/site/{site}/event` | Recent controller events (fallback chain across v1/v2 paths) |

### v1 Integration API (X-API-Key session — only when `api_key` is configured)

| Endpoint | What it returns |
|---|---|
| `/integration/v1/sites` | Site list with UUIDs |
| `/integration/v1/sites/{id}/firewall/policies` | Zone-based firewall policies |
| `/integration/v1/sites/{id}/firewall/zones` | Zone definitions and network membership |
| `/integration/v1/sites/{id}/dns/policies` | DNS / content-filtering policies |

For UDM-based controllers all legacy paths are prefixed with `/proxy/network/` — handled transparently by `_api_url()`. All v1 paths are prefixed with `/proxy/network/integration/v1`.

---

## Step 4 — Data Processing

`report/generator.py` transforms raw API responses into structured data the template can use directly. Each processor is a standalone function:

| Function | Input | Output |
|---|---|---|
| `_process_health()` | `stat/health` list | Flat dict with `wan_connections`, `www`, `vpn` |
| `_process_devices()` | `stat/device` list | Three lists: `aps`, `switches`, `gateways` |
| `_process_clients()` | `stat/sta` list | Client counts + top-10 consumers |
| `_process_inventory()` | `rest/user` list | Inventory rows + device-category breakdown |
| `_process_client_stats()` | `daily.user` + `hourly.user` records | Top-20 clients, category chart data, hourly pattern |
| `_process_wlans()` | `rest/wlanconf` + health | SSID list + WLAN client counts |
| `_process_networks()` | `rest/networkconf` | Filtered VLAN/network rows (WAN entries excluded) |
| `_process_firewall()` | `rest/firewallrule` + groups + networks | Rulesets with resolved names, security flags |
| `_process_fw_policies()` | v1 policies + zones + networks | Zone-based policy rows with readable filter summaries |
| `_process_dns_policies()` | v1 DNS policies | Policy rows with `available` flag |
| `_process_traffic_routes()` | v2 traffic routes | Policy routing rows with resolved names |
| `_process_port_forwards()` | `rest/portforward` | DNAT rule rows |
| `_process_wan_stats()` | `hourly.site` records | SVG path coordinates for the WAN chart |
| `_process_events()` | event list | Formatted timeline with severity levels |
| `_process_firmware()` | `stat/device` list | Firmware status per device, sorted by urgency |
| `_build_recommendations()` | aps, switches, health, alarms, firewall flags | Prioritized finding + action pairs |

### SVG Charts

Both the WAN utilization chart and the hourly activity bar chart are rendered **server-side** in Python as pre-computed coordinate strings passed to Jinja2. No client-side charting library is required — the SVG is embedded directly in the HTML and renders identically offline.

### Recommendations

`_build_recommendations()` applies threshold rules and returns `{priority, finding, action}` dicts:

| Check | Default threshold | Priority |
|---|---|---|
| AP TX retry rate | > 5% | Medium |
| AP recently rebooted | uptime < 7 days | High |
| AP offline | any | High |
| Switch port errors | > 100 errors | Medium |
| Active alarms | any | High |
| WAN status not `ok` | any | High |
| WAN_IN accept with no source restriction | any | High |

Thresholds are configurable under `report.thresholds` in `config.yaml`.

---

## Step 5 — HTML Rendering

`build_report()` loads `templates/report.html` via Jinja2's `FileSystemLoader` and calls `template.render(**ctx)`. Jinja2 auto-escaping prevents XSS from any controller-provided strings.

The rendered HTML is fully self-contained — no external CSS frameworks, no CDN dependencies, no web fonts. It renders correctly offline and can be emailed as an attachment.

**Themes** are implemented via CSS custom properties (`--var` tokens). Switching themes sets a `data-theme` attribute on `<html>` which activates an override block for each variable. Theme preference is saved in `localStorage`.

**Collapsible sections** are wired by a small inline script at the end of `<body>`. It iterates all `.section` elements, wraps their body content in a `.section-body` div, injects a chevron into each `.section-title`, and attaches click handlers. Collapse state is persisted per-section in `localStorage`.

---

## Step 6 — Output

Each run produces two files with matching timestamps:

```
reports/
  unifi_report_YYYYMMDD_HHMMSS.html      ← visual report
  json/
    unifi_snapshot_YYYYMMDD_HHMMSS.json  ← structured comparison snapshot
```

The JSON snapshot (`_build_snapshot()`) extracts the processed context into a compact, comparison-friendly structure covering WAN status, client counts, device inventory, firmware versions, WLAN config, network list, firewall summary, top-20 traffic clients, alarms, and recommendations. It is intentionally free of SVG paths, raw HTML, and ephemeral API fields.

The `reports/` directory and `reports/json/` are gitignored. Pass `--open` to the CLI to open the HTML report in your default browser immediately after generation.

---

## API Compatibility Notes

- The UniFi legacy API (`/api/s/{site}/...`) is unofficial and undocumented by Ubiquiti.
- The v1 integration API (`/integration/v1/...`) is the official documented API, available in **Network Application 10.1+**. It requires an API key generated in the controller UI.
- If any endpoint fails, the corresponding section is omitted from the report rather than aborting the run.
- `stat/dpi` (per-application DPI breakdown) returns empty on NA 10.x even when DPI is enabled. The Traffic Analysis section uses `stat/report/daily.user` and device fingerprinting as a practical alternative.
- Tested against **UniFi Network Application 10.3.58** on **UDM-SE (firmware 5.0.16)**.
