#!/usr/bin/env python3
"""Generate a UniFi Network Health Report from a self-hosted controller.

Usage:
    python generate_report.py                  # uses config.yaml, prompts for site
    python generate_report.py --config my.yaml
    python generate_report.py --open           # open in browser when done
    python generate_report.py --version        # show version
"""

__version__ = "1.0.0"

import argparse
import logging
import os
import sys
import webbrowser

import yaml

from unifi.client import UnifiClient
from report.generator import build_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config(path):
    if not os.path.exists(path):
        log.error("Config file not found: %s", path)
        log.error("Copy config.example.yaml to config.yaml and fill in your details.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def prompt_for_site(client):
    """Discover sites from the controller and let the user pick one.

    Returns the selected site ID (used in API paths, e.g. 'default').
    """
    sites = client.get_sites()

    if not sites:
        log.warning("No sites returned by controller — falling back to 'default'.")
        return "default"

    if len(sites) == 1:
        site = sites[0]
        site_id = site.get("name", "default")
        display = site.get("desc") or site_id
        print(f"\n  Only one site found: {display} — selecting automatically.\n")
        return site_id

    print("\n  Sites available on this controller:\n")
    for i, site in enumerate(sites, start=1):
        site_id = site.get("name", "?")
        display = site.get("desc") or site_id
        print(f"    [{i}]  {display}  (id: {site_id})")

    print()
    while True:
        try:
            raw = input("  Select a site [1]: ").strip()
            index = int(raw) - 1 if raw else 0
            if 0 <= index < len(sites):
                chosen = sites[index]
                chosen_id = chosen.get("name", "default")
                print(f"\n  Using site: {chosen.get('desc') or chosen_id}\n")
                return chosen_id
            print(f"  Please enter a number between 1 and {len(sites)}.")
        except (ValueError, EOFError):
            print(f"  Please enter a number between 1 and {len(sites)}.")


def main():
    parser = argparse.ArgumentParser(description="Generate a UniFi Network Health Report.")
    parser.add_argument("--config", default="config.yaml", help="Path to config file (default: config.yaml)")
    parser.add_argument("--open", action="store_true", dest="open_browser", help="Open the report in your browser when done")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--version", action="version", version=f"UniFi Network Health Report v{__version__}")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config = load_config(args.config)
    unifi_cfg = config.get("unifi", {})

    # Site is discovered interactively after login — remove it from the client constructor
    client = UnifiClient(
        host=unifi_cfg["host"],
        port=unifi_cfg.get("port", 443),
        username=unifi_cfg["username"],
        password=unifi_cfg["password"],
        verify_ssl=unifi_cfg.get("verify_ssl", False),
        api_key=unifi_cfg.get("api_key", ""),
    )

    try:
        log.info("Connecting to UniFi controller at %s:%s…", unifi_cfg["host"], unifi_cfg.get("port", 443))
        client.login()

        client.site = prompt_for_site(client)

        raw_data = client.collect_report_data()

        log.info("Building report…")
        _, output_path, snapshot_path = build_report(raw_data, config)

        print(f"\n  Report saved   → {output_path}")
        print(f"  Snapshot saved → {snapshot_path}\n")

        if args.open_browser:
            webbrowser.open(f"file://{os.path.abspath(output_path)}")

    except KeyboardInterrupt:
        log.info("Cancelled.")
    except Exception as e:
        log.error("Failed: %s", e)
        if args.debug:
            raise
        sys.exit(1)
    finally:
        client.logout()


if __name__ == "__main__":
    main()
