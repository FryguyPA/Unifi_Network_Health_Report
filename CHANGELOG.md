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

<!-- Add new versions above this line:

## [1.1.0] - YYYY-MM-DD

### Added
### Changed
### Fixed
### Removed

-->
