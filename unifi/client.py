"""UniFi Network Application API client.

Supports both UDM/UDM-Pro (port 443, /proxy/network/ prefix) and
standalone Network Application (port 8443, no prefix).
"""

import logging
import warnings
from datetime import datetime, timezone

import requests
import urllib3

log = logging.getLogger(__name__)


class UnifiClient:
    def __init__(self, host, port, username, password, site=None, verify_ssl=False):
        self.base_url = f"https://{host}:{port}"
        self.username = username
        self.password = password
        self.site = site
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self._is_udm = port == 443  # UDM uses /proxy/network/ prefix

        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.session.verify = False

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self):
        """Authenticate and store session cookies."""
        if self._is_udm:
            url = f"{self.base_url}/api/auth/login"
        else:
            url = f"{self.base_url}/api/login"

        payload = {"username": self.username, "password": self.password}
        resp = self.session.post(url, json=payload, timeout=15)
        resp.raise_for_status()

        # UDM returns a Bearer token in addition to cookies
        token = resp.headers.get("X-Updated-Csrf-Token") or resp.headers.get("x-csrf-token")
        if token:
            self.session.headers.update({"x-csrf-token": token})

        log.debug("Login successful to %s", self.base_url)

    def logout(self):
        try:
            if self._is_udm:
                self.session.post(f"{self.base_url}/api/auth/logout", timeout=10)
            else:
                self.session.get(f"{self.base_url}/api/logout", timeout=10)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_url(self, path):
        """Build a full API URL, adding /proxy/network prefix for UDM."""
        prefix = "/proxy/network" if self._is_udm else ""
        return f"{self.base_url}{prefix}{path}"

    def _get(self, path, params=None):
        url = self._api_url(path)
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", data)

    def _get_v2(self, path, params=None):
        """GET against the v2 API (UDM 3.x / Network Application 8.x+)."""
        prefix = "/proxy/network" if self._is_udm else ""
        url = f"{self.base_url}{prefix}/v2/api{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # v2 responses vary: list, or {data:[...]}, or {events:[...]}
        if isinstance(data, list):
            return data
        return data.get("data") or data.get("events") or data.get("items") or data

    # ------------------------------------------------------------------
    # Site discovery
    # ------------------------------------------------------------------

    def get_sites(self):
        """Return list of sites the authenticated user can access.

        Each entry is a dict with at least 'name' (display name) and
        'desc' (internal site ID used in API paths).
        """
        data = self._get("/api/self/sites")
        return sorted(data, key=lambda s: s.get("desc", "").lower())

    # ------------------------------------------------------------------
    # Site data endpoints
    # ------------------------------------------------------------------

    def get_health(self):
        """Overall site health (WAN status, client counts, etc.)."""
        return self._get(f"/api/s/{self.site}/stat/health")

    def get_clients(self):
        """All currently connected wireless and wired clients."""
        return self._get(f"/api/s/{self.site}/stat/sta")

    def get_all_clients(self):
        """All known clients including disconnected ones."""
        return self._get(f"/api/s/{self.site}/rest/user")

    def get_devices(self):
        """All UniFi devices: APs, switches, gateways."""
        return self._get(f"/api/s/{self.site}/stat/device")

    def get_events(self, limit=100):
        """Recent site events. Tries v1 and v2 API paths for broad controller compatibility."""
        # v2 API (UDM firmware 3.x+ / Network Application 8.x+)
        try:
            data = self._get_v2(f"/site/{self.site}/event", params={"limit": limit})
            log.debug("get_events succeeded via v2 API")
            return data[:limit] if isinstance(data, list) else []
        except Exception as e:
            log.debug("get_events v2 → %s", e)

        # v1 API fallbacks (older controllers)
        v1_attempts = [
            (f"/api/s/{self.site}/stat/event", {"_limit": limit}),
            (f"/api/s/{self.site}/stat/event", {"_limit": limit, "_sort": "-time"}),
            (f"/api/s/{self.site}/rest/event", {}),
        ]
        for path, params in v1_attempts:
            try:
                data = self._get(path, params=params or None)
                log.debug("get_events succeeded via %s", path)
                return data[:limit] if isinstance(data, list) else []
            except Exception as e:
                log.debug("get_events %s → %s", path, e)

        log.info("Events not available on this controller (Network Application 10.x removed the REST events endpoint).")
        return []

    def get_alarms(self):
        """Active alarms."""
        return self._get(f"/api/s/{self.site}/rest/alarm", params={"archived": False})

    def get_sysinfo(self):
        """Controller system info."""
        data = self._get(f"/api/s/{self.site}/stat/sysinfo")
        return data[0] if data else {}

    def get_dpi_stats(self):
        """Per-client DPI/application usage (may not be available on all setups)."""
        try:
            return self._get(f"/api/s/{self.site}/stat/dpi")
        except Exception:
            return []

    def get_port_forward(self):
        """Port forward rules."""
        return self._get(f"/api/s/{self.site}/rest/portforward")

    def get_wlans(self):
        """Configured SSIDs / wireless networks."""
        return self._get(f"/api/s/{self.site}/rest/wlanconf")

    def get_networks(self):
        """Configured networks (VLANs, WAN, VPN, etc.)."""
        return self._get(f"/api/s/{self.site}/rest/networkconf")

    def get_traffic_routes(self):
        """Per-device WAN-selection / policy routing rules (v2 API, NA 8+)."""
        try:
            data = self._get_v2(f"/site/{self.site}/trafficroutes")
            log.debug("get_traffic_routes: %d route(s)", len(data) if isinstance(data, list) else 0)
            return data if isinstance(data, list) else []
        except Exception as e:
            log.debug("get_traffic_routes failed (%s)", e)
            return []

    def get_port_forwards(self):
        """Port-forwarding / DNAT rules."""
        try:
            data = self._get(f"/api/s/{self.site}/rest/portforward")
            log.debug("get_port_forwards: %d rule(s)", len(data))
            return data
        except Exception as e:
            log.debug("get_port_forwards failed (%s)", e)
            return []

    def get_firewall_rules(self):
        """User-defined firewall rules for all rulesets.

        Tries the standard v1 path first, then a v2 fallback.  Logs the
        response count at DEBUG level so --debug reveals exactly what the
        controller returns.
        """
        path = f"/api/s/{self.site}/rest/firewallrule"
        try:
            data = self._get(path)
            log.debug("get_firewall_rules: %d rule(s) via %s", len(data), path)
            return data
        except Exception as e:
            log.debug("get_firewall_rules v1 failed (%s), trying v2 …", e)

        # v2 fallback (UDM-Pro firmware 3.x+ / Network Application 8.x+)
        try:
            data = self._get_v2(f"/site/{self.site}/firewall/rule")
            log.debug("get_firewall_rules: %d rule(s) via v2 API", len(data) if isinstance(data, list) else 0)
            return data if isinstance(data, list) else []
        except Exception as e2:
            log.debug("get_firewall_rules v2 failed (%s)", e2)

        log.info("Firewall rules endpoint not available on this controller.")
        return []

    def get_firewall_groups(self):
        """Firewall groups (address-group, port-group, ipv6-address-group)."""
        path = f"/api/s/{self.site}/rest/firewallgroup"
        try:
            data = self._get(path)
            log.debug("get_firewall_groups: %d group(s)", len(data))
            return data
        except Exception as e:
            log.debug("get_firewall_groups failed (%s)", e)
            return []

    # ------------------------------------------------------------------
    # Convenience: collect all report data in one call
    # ------------------------------------------------------------------

    def collect_report_data(self):
        """Fetch all data needed for the report. Returns a dict.

        Each endpoint is fetched independently — a failure on one section
        logs a warning and returns an empty result rather than aborting.
        """
        log.info("Fetching report data from %s (site: %s)…", self.base_url, self.site)

        def _safe(label, fn, default):
            try:
                return fn()
            except Exception as e:
                log.warning("Could not fetch %s (%s) — section will be empty.", label, e)
                return default

        return {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "health":           _safe("health",           self.get_health,               []),
            "clients":          _safe("clients",          self.get_clients,              []),
            "all_clients":      _safe("all_clients",      self.get_all_clients,          []),
            "devices":          _safe("devices",          self.get_devices,              []),
            "events":           _safe("events",           lambda: self.get_events(200),  []),
            "alarms":           _safe("alarms",           self.get_alarms,               []),
            "sysinfo":          _safe("sysinfo",          self.get_sysinfo,              {}),
            "wlans":            _safe("wlans",            self.get_wlans,                []),
            "networks":         _safe("networks",         self.get_networks,             []),
            "firewall_rules":    _safe("firewall_rules",    self.get_firewall_rules,    None),
            "firewall_groups":   _safe("firewall_groups",   self.get_firewall_groups,   []),
            "traffic_routes":    _safe("traffic_routes",    self.get_traffic_routes,    []),
            "port_forwards":     _safe("port_forwards",     self.get_port_forwards,     []),
        }
