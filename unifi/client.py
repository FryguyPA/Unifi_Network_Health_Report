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
    def __init__(self, host, port, username, password, site=None,
                 verify_ssl=False, api_key=None):
        self.base_url = f"https://{host}:{port}"
        self.username = username
        self.password = password
        self.site = site
        self.verify_ssl = verify_ssl
        self.api_key = api_key or ""
        self.v1_site_id = None        # resolved lazily from GET /v1/sites
        self.session = requests.Session()
        self._v1_session = None       # created lazily in _get_v1
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

    def _get_v1(self, path, params=None):
        """GET against the v1 integration API using X-API-Key auth.

        Returns a list of items on success, [] when the api_key is absent or
        the endpoint returns a non-200 status.  A separate requests.Session is
        used so v1 auth (header-based) never interferes with the cookie session.
        """
        if not self.api_key:
            return []

        # Lazy-create the v1 session
        if self._v1_session is None:
            self._v1_session = requests.Session()
            self._v1_session.verify = self.verify_ssl
            self._v1_session.headers["X-API-Key"] = self.api_key
            if not self.verify_ssl:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        url = f"{self.base_url}/proxy/network/integration/v1{path}"
        try:
            resp = self._v1_session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", data)
            return items if isinstance(items, list) else []
        except Exception as e:
            log.debug("v1 GET %s → %s", path, e)
            return []

    def _resolve_v1_site(self):
        """Return the v1 site UUID, resolving it from GET /v1/sites if needed."""
        if self.v1_site_id:
            return self.v1_site_id
        sites = self._get_v1("/sites")
        for s in sites:
            if s.get("internalReference") == self.site:
                self.v1_site_id = s["id"]
                return self.v1_site_id
        if sites:                        # fall back to first site
            self.v1_site_id = sites[0]["id"]
        return self.v1_site_id

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

    def get_wan_stats(self, hours=24, granularity="hourly"):
        """WAN TX/RX throughput history via stat/report endpoint.

        Returns a list of dicts with keys: time (Unix seconds), tx_bytes,
        rx_bytes — one record per interval (hourly by default).
        Tries both UDM and standalone paths; fails silently if unavailable.
        """
        import time as _time
        end_s   = int(_time.time())
        start_s = end_s - (hours * 3600)
        # UniFi controllers expect millisecond timestamps for start/end.
        # "time" must be listed in attrs to be included in the response.
        payload = {
            "attrs": ["wan-tx_bytes", "wan-rx_bytes", "time"],
            "start": start_s * 1000,
            "end":   end_s   * 1000,
        }
        path = f"/api/s/{self.site}/stat/report/{granularity}.site"
        try:
            url  = self._api_url(path)
            resp = self.session.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            records = data.get("data", data)
            if not isinstance(records, list):
                return []
            # Normalise: time field is sometimes ms, sometimes seconds
            out = []
            for r in records:
                ts = r.get("time", 0)
                if ts > 1e10:          # milliseconds → seconds
                    ts = ts / 1000
                out.append({
                    "time":     int(ts),
                    "tx_bytes": r.get("wan-tx_bytes") or 0,
                    "rx_bytes": r.get("wan-rx_bytes") or 0,
                })
            log.debug("get_wan_stats: %d %s record(s)", len(out), granularity)
            return out
        except Exception as e:
            log.debug("get_wan_stats failed (%s)", e)
            return []

    def get_dpi_stats(self):
        """Per-client DPI/application usage (may not be available on all setups)."""
        try:
            return self._get(f"/api/s/{self.site}/stat/dpi")
        except Exception:
            return []

    def get_client_stats(self, hours=24, granularity="daily"):
        """Per-client bandwidth history via stat/report/{granularity}.user.

        granularity: "daily" (one record per client per day) or
                     "hourly" (one record per client per hour).
        Returns raw records — each has user/oid (MAC), tx_bytes, rx_bytes, time.
        Multiple records may exist per client per interval; callers aggregate.
        Uses millisecond timestamps as required by the report API.
        """
        import time as _time
        end_s   = int(_time.time())
        start_s = end_s - (hours * 3600)
        payload = {
            "attrs": ["mac", "tx_bytes", "rx_bytes", "time"],
            "start": start_s * 1000,
            "end":   end_s   * 1000,
        }
        path = f"/api/s/{self.site}/stat/report/{granularity}.user"
        try:
            url  = self._api_url(path)
            resp = self.session.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            records = data.get("data", data)
            if not isinstance(records, list):
                return []
            log.debug("get_client_stats: %d record(s)", len(records))
            return records
        except Exception as e:
            log.debug("get_client_stats failed (%s)", e)
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
    # v1 API endpoints (require api_key)
    # ------------------------------------------------------------------

    def get_fw_policies(self):
        """Zone-based firewall policies (v1 API).  Returns (policies, zones)."""
        sid = self._resolve_v1_site()
        if not sid:
            return [], []
        policies = self._get_v1(f"/sites/{sid}/firewall/policies")
        zones    = self._get_v1(f"/sites/{sid}/firewall/zones")
        log.debug("get_fw_policies: %d policies, %d zones", len(policies), len(zones))
        return policies, zones

    def get_dns_policies(self):
        """DNS / content-filtering policies (v1 API)."""
        sid = self._resolve_v1_site()
        if not sid:
            return []
        data = self._get_v1(f"/sites/{sid}/dns/policies")
        log.debug("get_dns_policies: %d policies", len(data))
        return data

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
            "wan_stats":         _safe("wan_stats",         self.get_wan_stats,         []),
            "client_stats":        _safe("client_stats",        self.get_client_stats,                                []),
            "hourly_client_stats": _safe("hourly_client_stats", lambda: self.get_client_stats(hours=24, granularity="hourly"), []),
            # v1 API (requires api_key in config)
            "fw_policies":         _safe("fw_policies",         self.get_fw_policies,                             ([], [])),
            "dns_policies":        _safe("dns_policies",        self.get_dns_policies,                            []),
        }
