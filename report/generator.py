"""Transform raw UniFi API data into a structured context dict for the Jinja2 template."""

import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dateutil import tz
from jinja2 import Environment, FileSystemLoader

log = logging.getLogger(__name__)

# Device type codes returned by the API
_DEVICE_TYPE = {
    "ugw": "Gateway",
    "uap": "Access Point",
    "usw": "Switch",
    "udm": "Dream Machine",
    "uxg": "Next-Gen Gateway",
}

# Known event keys we care about for the timeline
_EVENT_PRIORITY = {
    "EVT_WU_Disconnected": "crit",
    "EVT_WU_Connected": "ok",
    "EVT_AP_Restarted": "crit",
    "EVT_AP_Connected": "ok",
    "EVT_AP_Disconnected": "crit",
    "EVT_SW_Restarted": "warn",
    "EVT_IDS_IpsAlert": "warn",
    "EVT_AD_Login": "info",
}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _bytes_to_human(b):
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _uptime_to_human(seconds):
    if not seconds:
        return "—"
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _ts_to_local(unix_ts, local_tz):
    if not unix_ts:
        return ""
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone(local_tz)
    return dt.strftime("%a %b %-d, %-I:%M %p")


def _pct(value, total):
    if not total:
        return 0.0
    return round(value / total * 100, 1)


# ------------------------------------------------------------------
# Data processing
# ------------------------------------------------------------------

def _process_health(health_list):
    """Extract WAN, LAN, WLAN and speedtest health into a flat dict.

    On Network Application 10.x both WAN connections live inside
    uptime_stats on the single 'wan' subsystem rather than as
    separate 'wan' / 'wan2' subsystems.
    """
    result = {"wan": {}, "lan": {}, "wlan": {}, "www": {}, "wan_connections": []}
    for item in health_list:
        sub = item.get("subsystem", "")
        if sub == "wan":
            result["wan"] = item
            wan_ip  = item.get("wan_ip", "—")
            isp     = item.get("isp_name") or item.get("isp_organization", "—")
            uptime_stats = item.get("uptime_stats", {})

            if uptime_stats:
                # Each key is "WAN", "WAN2", etc.
                for idx, (conn_name, stats) in enumerate(sorted(uptime_stats.items())):
                    avail = stats.get("availability", 0)
                    result["wan_connections"].append({
                        "name":         conn_name,
                        "ip":           wan_ip if idx == 0 else "—",
                        "isp":          isp    if idx == 0 else "—",
                        "availability": round(avail, 2),
                        "latency_avg":  stats.get("latency_average", "—"),
                        "uptime":       _uptime_to_human(stats.get("uptime", 0)),
                        "uptime_sec":   stats.get("uptime", 0),
                        "status":       "ok" if avail >= 99.9 else ("degraded" if avail > 95 else "down"),
                        "monitors":     stats.get("monitors", []),
                    })
            else:
                # Older firmware: single WAN entry, no uptime_stats
                status = item.get("status", "unknown")
                result["wan_connections"].append({
                    "name":         "WAN",
                    "ip":           wan_ip,
                    "isp":          isp,
                    "availability": 100.0 if status == "ok" else 0.0,
                    "latency_avg":  "—",
                    "uptime":       _uptime_to_human(item.get("uptime", 0)),
                    "uptime_sec":   item.get("uptime", 0),
                    "status":       status,
                    "monitors":     [],
                })

        elif sub == "wan2":
            # Older firmware separate wan2 subsystem
            result["wan2"] = item
            if not any(c["name"] == "WAN2" for c in result["wan_connections"]):
                status = item.get("status", "unknown")
                result["wan_connections"].append({
                    "name":         "WAN2",
                    "ip":           item.get("wan_ip", "—"),
                    "isp":          item.get("isp_name", "—"),
                    "availability": 100.0 if status == "ok" else 0.0,
                    "latency_avg":  "—",
                    "uptime":       _uptime_to_human(item.get("uptime", 0)),
                    "uptime_sec":   item.get("uptime", 0),
                    "status":       status,
                    "monitors":     [],
                })
        elif sub == "lan":
            result["lan"] = item
        elif sub == "wlan":
            result["wlan"] = item
        elif sub == "www":
            result["www"] = item

    return result


def _process_devices(device_list):
    """Split devices into APs, switches, and gateways with computed fields."""
    aps, switches, gateways = [], [], []
    now_ts = datetime.now(timezone.utc).timestamp()

    for d in device_list:
        dtype = d.get("type", "")
        name = d.get("name") or d.get("hostname") or d.get("mac", "Unknown")
        model = d.get("model", "—")
        uptime = d.get("uptime", 0)
        version = d.get("version", "—")
        state = d.get("state", 0)  # 1 = connected
        ip = d.get("ip", "—")

        base = {
            "name": name,
            "model": model,
            "ip": ip,
            "uptime": _uptime_to_human(uptime),
            "uptime_sec": uptime,
            "version": version,
            "connected": state == 1,
            "mac": d.get("mac", ""),
        }

        if dtype == "uap":
            radio_table = d.get("radio_table_stats", [])
            tx_retries = 0
            tx_packets = 0
            for r in radio_table:
                tx_retries += r.get("tx_retries", 0)
                tx_packets += r.get("tx_packets", 0) or 1

            retry_pct = _pct(tx_retries, tx_packets) if tx_packets else 0.0

            # channel info from radio_table (not stats)
            radios = d.get("radio_table", [])
            channels = []
            for r in radios:
                ch = r.get("channel")
                ht = r.get("ht") or r.get("channel_width")
                if ch:
                    channels.append(f"Ch {ch}" + (f"/{ht}MHz" if ht else ""))

            aps.append({
                **base,
                "clients": d.get("num_sta", 0),
                "retry_pct": retry_pct,
                "channels": ", ".join(channels) or "—",
                "satisfaction": d.get("satisfaction", None),
                "tx_bytes": d.get("tx_bytes", 0),
                "rx_bytes": d.get("rx_bytes", 0),
            })

        elif dtype == "usw":
            port_table = d.get("port_table", [])
            port_issues = []
            for p in port_table:
                if not p.get("up"):
                    continue
                rx_errors  = p.get("rx_errors",  0)
                rx_dropped = p.get("rx_dropped", 0)
                tx_errors  = p.get("tx_errors",  0)
                tx_dropped = p.get("tx_dropped", 0)
                total = rx_errors + rx_dropped + tx_errors + tx_dropped
                if total > 0:
                    port_issues.append({
                        "port":       p.get("name") or f"Port {p.get('port_idx', '?')}",
                        "port_idx":   p.get("port_idx", 0),
                        "speed":      p.get("speed", 0),
                        "rx_errors":  rx_errors,
                        "rx_dropped": rx_dropped,
                        "tx_errors":  tx_errors,
                        "tx_dropped": tx_dropped,
                        "total":      total,
                        "rx_bytes":   _bytes_to_human(p.get("rx_bytes", 0)),
                        "tx_bytes":   _bytes_to_human(p.get("tx_bytes", 0)),
                    })

            poe_budget_w = d.get("total_max_power", 0) or 0
            poe_used_w   = sum(float(p.get("poe_power") or 0) for p in port_table)
            poe_ports    = sum(1 for p in port_table if p.get("poe_enable"))

            switches.append({
                **base,
                "ports":        len(port_table),
                "port_issues":  port_issues,
                "poe_budget_w": round(poe_budget_w, 1),
                "poe_used_w":   round(poe_used_w,   1),
                "poe_ports":    poe_ports,
            })

        elif dtype in ("ugw", "udm", "uxg"):
            # Extract per-WAN-interface details (wan1 / wan2 top-level keys on UDM-SE)
            wan_ifaces = {}
            for key in ("wan1", "wan2"):
                iface = d.get(key) or {}
                if iface:
                    wan_ifaces[key.upper()] = {
                        "ip":           iface.get("ip", "—"),
                        "latency_ms":   iface.get("latency", "—"),
                        "availability": iface.get("availability", "—"),
                        "media":        iface.get("media", "—"),
                        "speed_mbps":   iface.get("speed", 0),
                        "rx_bytes":     _bytes_to_human(iface.get("rx_bytes", 0)),
                        "tx_bytes":     _bytes_to_human(iface.get("tx_bytes", 0)),
                    }

            # Fallback: scan port_table for wan/wan2 network_name
            if not wan_ifaces:
                for p in d.get("port_table", []):
                    net = p.get("network_name", "").lower()
                    if net in ("wan", "wan2") and p.get("ip"):
                        wan_ifaces[net.upper()] = {
                            "ip":         p.get("ip", "—"),
                            "latency_ms": "—",
                            "media":      p.get("media", "—"),
                            "speed_mbps": p.get("speed", 0),
                            "rx_bytes":   _bytes_to_human(p.get("rx_bytes", 0)),
                            "tx_bytes":   _bytes_to_human(p.get("tx_bytes", 0)),
                        }

            wan_iface = (d.get("uplink") or {})
            gateways.append({
                **base,
                "wan_ip":    wan_iface.get("ip", "—"),
                "wan_ifaces": wan_ifaces,
                "loadavg":   d.get("sys_stats", {}).get("loadavg_1", "—"),
                "mem_pct":   _pct(
                    d.get("sys_stats", {}).get("mem_used", 0),
                    d.get("sys_stats", {}).get("mem_total", 1)
                ),
                "cpu_pct": d.get("sys_stats", {}).get("cpu", 0),
            })

    return aps, switches, gateways


def _process_clients(client_list):
    """Sort clients by bandwidth and return top consumers + summary stats."""
    active = [c for c in client_list if c.get("_is_guest_by_uap") is not None or True]

    for c in active:
        c["_total_bytes"] = (c.get("tx_bytes", 0) or 0) + (c.get("rx_bytes", 0) or 0)
        c["_display_name"] = (
            c.get("name")
            or c.get("hostname")
            or c.get("mac", "Unknown")
        )

    top = sorted(active, key=lambda x: x["_total_bytes"], reverse=True)[:10]

    top_consumers = []
    for c in top:
        if c["_total_bytes"] == 0:
            continue
        top_consumers.append({
            "name": c["_display_name"],
            "ip": c.get("ip", "—"),
            "mac": c.get("mac", ""),
            "total": _bytes_to_human(c["_total_bytes"]),
            "download": _bytes_to_human(c.get("rx_bytes", 0)),
            "upload": _bytes_to_human(c.get("tx_bytes", 0)),
            "network": c.get("network", "—"),
            "is_guest": c.get("is_guest", False),
            "is_wired": c.get("is_wired", False),
        })

    return {
        "total": len(active),
        "wireless": sum(1 for c in active if not c.get("is_wired")),
        "wired": sum(1 for c in active if c.get("is_wired")),
        "guests": sum(1 for c in active if c.get("is_guest")),
        "top_consumers": top_consumers,
    }


def _process_events(event_list, local_tz, limit=20):
    """Format the most recent events for the timeline."""
    timeline = []
    for e in event_list[:limit]:
        key = e.get("key", "")
        msg = e.get("msg", key)
        ts = e.get("time", 0) / 1000 if e.get("time", 0) > 1e10 else e.get("time", 0)
        level = _EVENT_PRIORITY.get(key, "info")

        timeline.append({
            "time": _ts_to_local(ts, local_tz),
            "level": level,
            "message": msg,
            "key": key,
        })
    return timeline


def _process_wlans(wlan_list, health):
    """Process SSID config + WLAN health subsystem into a summary dict."""
    wlan_health = health.get("wlan", {})

    ssids = []
    for w in wlan_list:
        bands = w.get("wlan_bands") or []
        ssids.append({
            "name":     w.get("name", "—"),
            "enabled":  w.get("enabled", False),
            "security": (w.get("security") or "open").upper().replace("WPAPSK", "WPA2").replace("WPA3", "WPA3"),
            "bands":    ", ".join(b.upper() for b in bands) if bands else "—",
            "is_guest": w.get("is_guest", False),
        })

    return {
        "ssids":            ssids,
        "user_clients":     wlan_health.get("num_user",  0),
        "guest_clients":    wlan_health.get("num_guest", 0),
        "iot_clients":      wlan_health.get("num_iot",   0),
        "num_aps":          wlan_health.get("num_adopted", 0),
        "num_disconnected": wlan_health.get("num_disconnected", 0),
        "status":           wlan_health.get("status", "unknown"),
    }


def _process_vpn(health):
    """Extract VPN status from health subsystem."""
    vpn = health.get("vpn", {})
    return {
        "enabled":        vpn.get("remote_user_enabled",   False),
        "active_sessions": vpn.get("remote_user_num_active", 0),
        "inactive_users":  vpn.get("remote_user_num_inactive", 0),
        "rx_bytes":       _bytes_to_human(vpn.get("remote_user_rx_bytes", 0) or 0),
        "tx_bytes":       _bytes_to_human(vpn.get("remote_user_tx_bytes", 0) or 0),
        "site_to_site":   vpn.get("site_to_site_enabled", False),
    }


# UniFi device category codes (dev_cat field on rest/user records)
_DEV_CAT_LABEL = {
    0:  "Unknown",
    1:  "Computer",
    2:  "Access Point",
    3:  "Router",
    4:  "Switch",
    5:  "NAS",
    6:  "VoIP Phone",
    7:  "IP Camera",
    8:  "Smart TV",
    9:  "Raspberry Pi",
    10: "Game Console",
    11: "Printer",
    12: "Wireless Device",
    13: "Tablet",
    14: "Mobile Phone",
    15: "Laptop",
    16: "Desktop",
    17: "Gaming Device",
    18: "Smart Speaker",
    19: "Streaming Device",
    20: "Smart Home Hub",
    21: "Set-top Box",
    22: "Smart Watch",
    23: "Server",
    40: "Smartphone",
    41: "Apple Device",
    42: "IoT Device",
    43: "Smart Home",
    44: "iPhone / iPad",
    45: "Android Phone",
    46: "Mac",
    47: "Media Device",
    48: "Smart TV",
    49: "Smart Home",
    50: "IP Camera",
    51: "Nest / Google",
    52: "Sonos / Audio",
    53: "Amazon Echo",
}

# Roll fine-grained categories into broader display groups
_DEV_CAT_GROUP = {
    0:  "Unknown",
    1:  "Computers",
    2:  "Network",
    3:  "Network",
    4:  "Network",
    5:  "Computers",
    6:  "Phones",
    7:  "Cameras",
    8:  "Media",
    9:  "Computers",
    10: "Gaming",
    11: "Printers",
    12: "Other",
    13: "Phones",
    14: "Phones",
    15: "Computers",
    16: "Computers",
    17: "Gaming",
    18: "Media",
    19: "Media",
    20: "IoT",
    21: "Media",
    22: "Phones",
    23: "Computers",
    40: "Phones",
    41: "Phones",
    42: "IoT",
    43: "IoT",
    44: "Phones",
    45: "Phones",
    46: "Computers",
    47: "Media",
    48: "Media",
    49: "IoT",
    50: "Cameras",
    51: "IoT",
    52: "Media",
    53: "IoT",
}

_NETWORK_PURPOSE_LABEL = {
    "corporate":       "LAN",
    "guest":           "Guest",
    "vlan-only":       "VLAN",
    "remote-user-vpn": "VPN",
    "wan":             "WAN",
    "vpn":             "VPN",
}


def _process_networks(network_list):
    """Filter and format network/VLAN list, excluding raw WAN entries."""
    networks = []
    for n in network_list:
        purpose = n.get("purpose", "")
        if purpose == "wan":
            continue
        networks.append({
            "name":    n.get("name", "—"),
            "purpose": _NETWORK_PURPOSE_LABEL.get(purpose, purpose.title()),
            "vlan":    n.get("vlan") or "untagged",
            "subnet":  n.get("ip_subnet") or "—",
            "dhcp":    bool(n.get("dhcpd_enabled")),
        })
    return networks


def _process_firmware(device_list):
    """Build a firmware status row for every device."""
    type_order = {"udm": 0, "ugw": 1, "uxg": 2, "usw": 3, "uap": 4}
    rows = []
    for d in device_list:
        dtype   = d.get("type", "")
        upgradable = d.get("upgradable", False)
        rows.append({
            "name":       d.get("name") or d.get("hostname") or d.get("mac", "—"),
            "type":       _DEVICE_TYPE.get(dtype, dtype.upper()),
            "model":      d.get("model", "—"),
            "version":    d.get("version", "—"),
            "upgradable": upgradable,
            "upgrade_to": d.get("upgrade_to_firmware") or "",
            "connected":  d.get("state", 0) == 1,
        })
    rows.sort(key=lambda x: (not x["upgradable"], type_order.get(
        next((d.get("type","") for d in device_list if d.get("name")==x["name"]), ""), 9), x["name"]))
    return rows


def _process_inventory(all_clients_list, local_tz):
    """Process rest/user records into a client inventory table and device-type breakdown.

    rest/user returns all known clients (including disconnected ones) with
    UniFi's built-in OUI resolution and device fingerprinting fields.
    """
    _GROUP_ORDER = ["Computers", "Phones", "IoT", "Media", "Gaming", "Cameras",
                    "Printers", "Network", "Other", "Unknown"]

    rows = []
    category_counts = {}

    for c in all_clients_list:
        dev_cat   = c.get("dev_cat")
        cat_label = _DEV_CAT_LABEL.get(dev_cat, "Unknown") if dev_cat is not None else "Unknown"
        cat_group = _DEV_CAT_GROUP.get(dev_cat, "Unknown") if dev_cat is not None else "Unknown"

        category_counts[cat_group] = category_counts.get(cat_group, 0) + 1

        # Prefer dev_family when it's a descriptive string (e.g. "iPhone", "MacBook Pro").
        # UniFi sometimes returns dev_family as an integer code — ignore those and fall
        # back to our cat_label mapping so the column never shows a bare number.
        dev_family_raw = c.get("dev_family")
        if isinstance(dev_family_raw, str) and dev_family_raw.strip():
            device_type = dev_family_raw
        else:
            device_type = cat_label

        last_seen_ts = c.get("last_seen", 0) or 0
        first_seen_ts = c.get("first_seen", 0) or 0

        rows.append({
            "hostname":    c.get("hostname") or c.get("name") or c.get("mac", ""),
            "ip":          c.get("last_ip") or "—",
            "mac":         c.get("mac", ""),
            "oui":         c.get("oui") or "—",
            "device_type": device_type,
            "cat_group":   cat_group,
            "network":     c.get("last_connection_network_name") or "—",
            "is_wired":    c.get("is_wired", False),
            "is_guest":    c.get("is_guest", False),
            "last_seen":   _ts_to_local(last_seen_ts, local_tz) if last_seen_ts else "—",
            "last_seen_ts": last_seen_ts,
            "first_seen":  _ts_to_local(first_seen_ts, local_tz) if first_seen_ts else "—",
        })

    rows.sort(key=lambda x: x["last_seen_ts"], reverse=True)

    breakdown = [
        {"label": grp, "count": category_counts[grp]}
        for grp in _GROUP_ORDER
        if category_counts.get(grp, 0) > 0
    ]

    return {
        "rows":      rows,
        "total":     len(rows),
        "breakdown": breakdown,
    }


def _build_recommendations(aps, switches, health, alarms, thresholds):
    """Generate a prioritized list of actionable recommendations."""
    recs = []

    # AP retry rate
    retry_threshold = thresholds.get("ap_retry_pct", 5.0)
    for ap in aps:
        if ap["retry_pct"] > retry_threshold:
            recs.append({
                "priority": "medium",
                "finding": f"{ap['name']} TX retry rate {ap['retry_pct']:.1f}% (threshold {retry_threshold}%)",
                "action": "Check for RF interference or reduce channel width on 5 GHz radio.",
            })

    # AP uptime (reboots)
    reboot_days = thresholds.get("ap_reboot_days", 7)
    reboot_threshold_sec = reboot_days * 86400
    for ap in aps:
        if ap["connected"] and ap["uptime_sec"] < reboot_threshold_sec and ap["uptime_sec"] > 0:
            recs.append({
                "priority": "high",
                "finding": f"{ap['name']} rebooted recently (uptime: {ap['uptime']})",
                "action": "Check PoE supply and review event log for crash/power loss cause.",
            })

    # Disconnected devices
    for ap in aps:
        if not ap["connected"]:
            recs.append({
                "priority": "high",
                "finding": f"AP {ap['name']} is offline",
                "action": "Verify power, PoE port, and network connectivity.",
            })

    # Switch port errors
    error_threshold = thresholds.get("switch_error_rate", 100)
    for sw in switches:
        for p in sw.get("port_issues", []):
            total_err = p["rx_errors"] + p["tx_errors"]
            if total_err > error_threshold:
                recs.append({
                    "priority": "medium",
                    "finding": f"{sw['name']} {p['port']}: {total_err} errors",
                    "action": "Replace cable or SFP; check connected device for NIC errors.",
                })

    # Active alarms
    for alarm in alarms[:5]:
        msg = alarm.get("msg", "Unknown alarm")
        recs.append({
            "priority": "high",
            "finding": f"Active alarm: {msg}",
            "action": "Review in UniFi dashboard and resolve or archive.",
        })

    # Gateway health
    wan = health.get("wan", {})
    if wan.get("status") != "ok":
        recs.append({
            "priority": "high",
            "finding": f"WAN status is '{wan.get('status', 'unknown')}'",
            "action": "Check ISP connection and gateway WAN port.",
        })

    return recs


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------

def build_report(raw_data, config):
    """Process raw API data and render the HTML report. Returns (html_str, output_path)."""
    report_cfg = config.get("report", {})
    site_name = report_cfg.get("site_name", "My Network")
    output_dir = report_cfg.get("output_dir", "reports")
    tz_name = report_cfg.get("timezone", "UTC")
    thresholds = report_cfg.get("thresholds", {})

    local_tz = tz.gettz(tz_name) or timezone.utc

    now = datetime.now(local_tz)
    generated_at = now.strftime("%B %-d, %Y at %-I:%M %p %Z")

    health   = _process_health(raw_data.get("health",   []))
    aps, switches, gateways = _process_devices(raw_data.get("devices", []))
    clients  = _process_clients(raw_data.get("clients", []))
    events   = _process_events(raw_data.get("events",   []), local_tz)
    alarms   = raw_data.get("alarms",  [])
    sysinfo  = raw_data.get("sysinfo", {})
    wlans    = _process_wlans(raw_data.get("wlans", []), health)
    vpn      = _process_vpn(health)
    networks = _process_networks(raw_data.get("networks", []))
    firmware = _process_firmware(raw_data.get("devices",  []))
    inventory = _process_inventory(raw_data.get("all_clients", []), local_tz)
    recommendations = _build_recommendations(aps, switches, health, alarms, thresholds)

    # Merge per-interface IP/media from gateway device into wan_connections
    gw_wan_ifaces = {}
    for gw in gateways:
        gw_wan_ifaces.update(gw.get("wan_ifaces", {}))

    wan_connections = health.get("wan_connections", [])
    for conn in wan_connections:
        iface = gw_wan_ifaces.get(conn["name"], {})
        if iface.get("ip") and iface["ip"] != "—":
            conn["ip"] = iface["ip"]
        conn["media"]     = iface.get("media", "—")
        conn["speed_mbps"] = iface.get("speed_mbps", "—")
    wan_up = all(c["status"] == "ok" for c in wan_connections) if wan_connections else (health.get("wan", {}).get("status") == "ok")

    # Speedtest data from www subsystem
    www = health.get("www", {})
    speedtest = {
        "download_mbps": www.get("xput_down"),
        "upload_mbps":   www.get("xput_up"),
        "ping_ms":       www.get("speedtest_ping"),
        "latency_ms":    www.get("latency"),
        "last_run":      _ts_to_local(www.get("speedtest_lastrun"), local_tz) if www.get("speedtest_lastrun") else None,
    }

    ctx = {
        "site_name": site_name,
        "generated_at": generated_at,
        "controller_version": sysinfo.get("version", "—"),

        # KPIs
        "wan_up": wan_up,
        "wan_status_text": "Online" if wan_up else "Degraded / Offline",
        "wan_connection_count": len(wan_connections),
        "client_count": clients["total"],
        "client_wireless": clients["wireless"],
        "client_wired": clients["wired"],
        "client_guests": clients["guests"],
        "alarm_count": len(alarms),

        # WAN detail
        "wan_connections": wan_connections,
        "speedtest": speedtest,
        "health": health,
        "gateways": gateways,

        # Clients
        "clients": clients,

        # Devices
        "aps":      sorted(aps, key=lambda x: x["name"]),
        "switches": switches,

        # WLAN + VPN
        "wlans": wlans,
        "vpn":   vpn,

        # Networks / VLANs
        "networks": networks,

        # Firmware
        "firmware": firmware,
        "firmware_upgradable": sum(1 for f in firmware if f["upgradable"]),

        # Client inventory + device fingerprinting
        "inventory": inventory,

        # Events & alerts
        "events": events,
        "alarms": alarms,

        # Recommendations
        "recommendations": recommendations,
        "rec_count_high":   sum(1 for r in recommendations if r["priority"] == "high"),
        "rec_count_medium": sum(1 for r in recommendations if r["priority"] == "medium"),
    }

    # Render template
    templates_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    template = env.get_template("report.html")
    html = template.render(**ctx)

    # Write output file
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"unifi_report_{now.strftime('%Y%m%d_%H%M%S')}.html"
    output_path = os.path.join(output_dir, filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    log.info("Report written to %s", output_path)
    return html, output_path
