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

<!-- Add new versions above this line:

## [1.3.0] - YYYY-MM-DD

### Added
### Changed
### Fixed
### Removed

-->
