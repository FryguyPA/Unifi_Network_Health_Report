# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- Initial project scaffolding
- `unifi/client.py` — UniFi API client with support for UDM/UDM-Pro (port 443) and standalone Network Application (port 8443)
- `report/generator.py` — data processing pipeline: parses health, devices, clients, events, and alarms into a structured report context
- `templates/report.html` — self-contained Jinja2 HTML template styled to match UniFi's design language
- `generate_report.py` — CLI entry point with `--open`, `--config`, and `--debug` flags
- `config.example.yaml` — documented configuration template
- Auto-generated recommendations based on configurable thresholds (AP retry rate, recent reboots, offline devices, switch port errors, active alarms)
- Reports saved as timestamped HTML files in the `reports/` output directory

---

<!-- Add new versions above this line using the format below:

## [1.1.0] - YYYY-MM-DD

### Added
- ...

### Changed
- ...

### Fixed
- ...

### Removed
- ...

-->
