# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.0.0] - 2026-05-07

Initial public release.

### Added

**Core**
- `unifi/client.py` — UniFi API client supporting UDM/UDM-Pro (port 443, `/proxy/network/` prefix) and standalone Network Application (port 8443)
- `report/generator.py` — full data processing pipeline transforming raw API responses into a structured Jinja2 template context
- `templates/report.html` — self-contained HTML report with no external dependencies; renders offline and is safe to email
- `generate_report.py` — CLI entry point with `--open`, `--config`, `--debug`, and `--version` flags
- `config.example.yaml` — fully documented configuration template

**Report Sections**
- KPI summary row: WAN status, connected clients, access point count, active alarms
- Gateway / WAN table with dual-WAN support — IP, ISP, media type, availability %, latency, uptime, and status badge per connection
- Speedtest row (download / upload / ping) pulled from `www` subsystem
- Top bandwidth consumers by device with network/VLAN badge
- Wireless Networks — SSID table with security, bands, and guest flag; client counts by type (user / IoT / guest)
- VPN status — remote user sessions, site-to-site toggle, session traffic totals
- Networks & VLANs — all configured networks with type, VLAN ID, subnet, and DHCP status
- Access point grid — per-AP clients, TX retry %, channel, uptime, and auto-generated health badge
- Switches table — port count, PoE budget bar (used W / total W), and port error dropdowns with full RX/TX error breakdown
- Firmware compliance table — every device with version and upgrade availability
- Event timeline (where available; silently skipped on Network Application 10.x which removed the REST events endpoint)
- Recommendations — auto-generated prioritized action items based on configurable thresholds

**Site Discovery**
- Interactive site picker after login — discovers all accessible sites and prompts the user to choose; auto-selects when only one site exists

**Compatibility**
- Graceful per-endpoint error handling — a 404 or unavailable endpoint logs a warning and returns an empty section rather than aborting the run
- Dual-WAN IP resolution from both `uptime_stats` (health subsystem) and `wan1`/`wan2` device fields
- Events fallback chain across v1 and v2 API paths for cross-version compatibility
- Tested against UniFi Network Application 10.3.58 on UDM-SE (firmware 5.0.16)

**Project**
- Apache 2.0 license
- `config.yaml` and `reports/` directory gitignored
- `README.md`, `CHANGELOG.md`, `HOWITWORKS.md` documentation

---

## [1.1.0] - 2026-05-08

### Added

**Client Inventory & Device Fingerprinting**
- New `get_all_clients()` method in `unifi/client.py` — fetches `rest/user` endpoint which returns all known devices (including disconnected), with UniFi's built-in OUI resolution and fingerprinting data (`dev_cat`, `dev_family`, `oui`, `confidence`)
- `_process_inventory()` in `report/generator.py` — transforms `rest/user` records into a structured inventory with:
  - `_DEV_CAT_LABEL` — maps 40+ UniFi `dev_cat` integer codes to human-readable device type names
  - `_DEV_CAT_GROUP` — rolls fine-grained categories into 10 broad display groups (Computers, Phones, IoT, Media, Gaming, Cameras, Printers, Network, Other, Unknown)
  - Sorted by `last_seen` descending; devices with no last-seen timestamp listed last
  - MAC address used as hostname fallback for unnamed devices
- **Client Inventory section** in `templates/report.html`:
  - Device-type breakdown cards — always-visible count per group (e.g. Computers: 12, Phones: 34, IoT: 47)
  - Full inventory table inside a collapsible `<details>` — hostname, last IP, MAC, manufacturer (OUI), device type, network badge, wired/WiFi + guest badges, last seen timestamp
  - All 8 columns are **sortable** — click any header to sort ascending/descending with a ▲/▼ indicator; IP addresses sort numerically by octet; timestamps sort by raw Unix value behind the formatted label

### Fixed
- `dev_family` integer bug — UniFi sometimes returns `dev_family` as a numeric code rather than a descriptive string; the field is now type-checked (`isinstance(str)`) so integer values fall back to the `_DEV_CAT_LABEL` mapping instead of rendering as a bare number in the Device Type column

---

---

## [1.2.0] - 2026-05-08

### Added

**Firewall Rules**
- `get_firewall_rules()` and `get_firewall_groups()` methods in `unifi/client.py` — fetches `rest/firewallrule` and `rest/firewallgroup` endpoints; both integrated into `collect_report_data()` with `_safe()` error isolation
- `_process_firewall()` in `report/generator.py`:
  - Resolves firewall group IDs and network config IDs to human-readable names so Source/Destination columns never show raw UUIDs
  - Groups rules by ruleset (`WAN_IN`, `WAN_OUT`, `WAN_LOCAL`, `LAN_IN`, etc.) and sorts within each group by `rule_index`
  - Security flag: WAN_IN `accept` rules with no source restriction are flagged as high-priority findings
  - Disabled rules are labeled inline
- **Firewall Rules section** in `templates/report.html`:
  - Ruleset summary strip — one card per active ruleset with color-coded top border (blue = WAN, amber = Guest, purple = LAN) and a red flag count badge when issues exist
  - Per-ruleset `<details>` tables — rule index, name, action badge (green Accept / red Drop / yellow Reject), protocol, source, destination, port, enabled status, and logging indicator; rulesets with security flags open by default
  - Firewall Groups collapsible table — group name, type, and member list (click to expand members)
- Firewall security flags are now included in the Recommendations section alongside AP, switch, and alarm findings

---

## [1.3.0] - 2026-05-11

### Added

**Themes**
- Four built-in visual themes selectable from the report header: Light (default), Dark Terminal, Slate & Amber, Deep Navy
- CSS custom-property system — every color token is a variable; switching themes is a single `data-theme` attribute change on `<html>`
- Theme preference persisted in `localStorage` — choice survives page reloads and opening future reports
- Inline-style override rules (`[style*="color:#xxxxxx"]` attribute selectors with `!important`) ensure hardcoded Python-generated colors are also remapped on dark themes

**Collapsible Sections**
- Every report section is now collapsible — click its heading to toggle open/closed
- Chevron indicator rotates 90° when collapsed; section border and bottom margin are suppressed so collapsed sections take minimal vertical space
- Collapse state persisted per-section in `localStorage` using derived section IDs — collapsed sections stay collapsed when you re-open the report

**WAN Utilization Chart**
- New inline SVG area chart showing 24-hour WAN TX/RX throughput (Mbps) fetched from `stat/report/hourly.site`
- Blue fill = download, green fill = upload; hover tooltips show exact Mbps per hour
- `get_wan_stats()` in `unifi/client.py` uses millisecond timestamps and includes `"time"` in the `attrs` payload (both required by the controller)
- `_process_wan_stats()` in `report/generator.py` pre-computes all SVG coordinates server-side — no client-side JS charting library required

**Traffic Analysis**
- New section using `stat/report/daily.user` (24 h per-client totals) and `stat/report/hourly.user` (per-client per-hour)
- **Device-category breakdown** — joins client bandwidth with `rest/user` fingerprinting (`dev_cat`) to aggregate traffic by group (Computers, Phones, IoT, Media, Gaming, etc.); displayed as a horizontal bar chart with color-coded categories
- **Hourly activity pattern** — 24-bar SVG chart showing total network bandwidth by hour of day; bar opacity scales with utilization so peak periods stand out
- **Top-20 clients table** — ranked by 24 h total bytes with download/upload columns and a gradient share bar; hostname resolved from connected + historical client records
- `get_client_stats(granularity=)` supports both `"daily"` and `"hourly"` granularity
- MAC address field shimmed: NA 10.x returns MAC in `"user"` / `"oid"` fields rather than `"mac"`

**v1 API Integration**
- `UnifiClient` accepts optional `api_key=` constructor parameter (read from `config.yaml → unifi.api_key`)
- `_get_v1(path)` — dedicated `requests.Session` with `X-API-Key` header, completely separate from the cookie-auth session; returns `[]` gracefully when no key is configured
- `_resolve_v1_site()` — calls `GET /integration/v1/sites`, matches by `internalReference`, and caches the site UUID required for all v1 calls
- `get_fw_policies()` — fetches zone-based firewall policies and zones in a single call
- `get_dns_policies()` — fetches DNS / content-filtering policies
- `config.example.yaml` updated with `api_key` field, instructions for where to generate it, and a note that the field is optional

**Zone Firewall Policies section** (requires `api_key`)
- Zone summary cards — one card per zone (Gateway, Internal, External, VPN, DMZ, Hotspot) with network count and origin type
- Policy table sorted by index — name, Allow/Block/Reject badge, source zone → destination zone, traffic filter summary (resolves network IDs to names, shows domains, IPs, or port ranges), and logging indicator
- Traffic filter decoder (`_summarize_traffic_filter()`) handles NETWORK, DOMAIN, PORT, and IP_ADDRESS filter types

**DNS & Content Filtering section** (requires `api_key`)
- Lists configured DNS policies with action, categories, and enabled status
- Renders "no policies configured" placeholder when the endpoint returns an empty list
- Section hidden entirely when no `api_key` is set

**JSON Snapshots**
- Every report run now writes a companion `reports/json/unifi_snapshot_<timestamp>.json` alongside the HTML
- Snapshot contains all comparison-relevant fields: WAN status + connections, client counts, device inventory with firmware versions, WLAN config, network list, firewall summary, top-20 traffic clients, alarms, and recommendations
- `_build_snapshot()` in `report/generator.py` builds the structure from the processed context (not raw API data) — always clean and JSON-serializable
- `generate_report.py` prints both output paths on completion
- `build_report()` return signature updated to `(html, html_path, snapshot_path)`

### Changed

- **Report section order** redesigned for better information hierarchy:
  Recommendations → Gateway/WAN → WAN Chart → Access Points → Switches → Firmware → Traffic Analysis → Top Consumers → Client Inventory → Wireless → VPN → Networks → Zone Firewall → DNS Policies → Legacy Firewall → Events
- `section-title` elements now use `display:flex` with a right-aligned chevron; clicking the title toggles the section instead of requiring a separate button
- `get_client_stats()` refactored to accept a `granularity` parameter instead of having a separate method per granularity

<!-- Add new versions above this line:

## [1.4.0] - YYYY-MM-DD

### Added
### Changed
### Fixed
### Removed

-->
