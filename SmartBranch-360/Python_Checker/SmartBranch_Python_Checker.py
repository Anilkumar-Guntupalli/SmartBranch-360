
#!/usr/bin/env python3
"""SmartBranch 360 configuration assurance checker."""

from __future__ import annotations
import argparse
import ipaddress
import re
import sys
from pathlib import Path
from typing import Any

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def finding(status: str, message: str, suggestion: str | None = None):
    item = {"status": status, "message": message}
    if suggestion:
        item["suggestion"] = suggestion
    return item


def print_finding(item):
    print(f"[{item['status']}] {item['message']}")
    if item.get("suggestion"):
        print(f"        Suggested fix: {item['suggestion']}")


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML is not installed.")
        print("Run: python3 -m pip install pyyaml")
        raise SystemExit(2)
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        print(f"ERROR reading {path}: {exc}")
        raise SystemExit(2)
    if not isinstance(data, dict):
        print("ERROR: YAML must contain a top-level mapping.")
        raise SystemExit(2)
    return data


def validate_plan(plan):
    results = []
    expected = {
        10: ("EMPLOYEE", "10.10.10.0/24", "10.10.10.1"),
        20: ("GUEST", "10.10.20.0/24", "10.10.20.1"),
        30: ("SERVER", "10.10.30.0/24", "10.10.30.1"),
        99: ("MANAGEMENT", "10.10.99.0/24", "10.10.99.1"),
    }
    vlans = plan.get("vlans", [])
    by_id = {}
    for v in vlans if isinstance(vlans, list) else []:
        if isinstance(v, dict):
            try:
                by_id[int(v["id"])] = v
            except (KeyError, TypeError, ValueError):
                pass

    for vid, (name, subnet, gateway) in expected.items():
        v = by_id.get(vid)
        if not v:
            results.append(finding(FAIL, f"VLAN {vid} {name} is missing.",
                                  f"Create VLAN {vid} named {name}."))
            continue
        actual_name = str(v.get("name", "")).upper()
        actual_subnet = str(v.get("subnet", ""))
        actual_gateway = str(v.get("gateway", ""))

        results.append(finding(PASS, f"VLAN {vid} name = {name}")
                        if actual_name == name else
                        finding(FAIL, f"VLAN {vid} name is {actual_name or '<missing>'}; expected {name}.",
                                f"Rename VLAN {vid} to {name}."))
        results.append(finding(PASS, f"VLAN {vid} subnet = {subnet}")
                        if actual_subnet == subnet else
                        finding(FAIL, f"VLAN {vid} subnet is {actual_subnet or '<missing>'}; expected {subnet}.",
                                f"Use subnet {subnet}."))
        results.append(finding(PASS, f"VLAN {vid} gateway = {gateway}")
                        if actual_gateway == gateway else
                        finding(FAIL, f"VLAN {vid} gateway is {actual_gateway or '<missing>'}; expected {gateway}.",
                                f"Set gateway to {gateway}."))

        try:
            if ipaddress.ip_address(actual_gateway) in ipaddress.ip_network(actual_subnet, strict=False):
                results.append(finding(PASS, f"VLAN {vid} gateway {actual_gateway} belongs to {actual_subnet}"))
            else:
                results.append(finding(FAIL, f"VLAN {vid} gateway {actual_gateway} is outside {actual_subnet}.",
                                      "Choose a gateway inside the VLAN subnet."))
        except ValueError:
            results.append(finding(FAIL, f"VLAN {vid} has an invalid subnet/gateway.",
                                  "Check the IPv4 addressing."))

    services = plan.get("services", {})
    for key, label in {
        "dhcp": "DHCP", "dns": "DNS", "nat": "NAT",
        "inter_vlan_routing": "inter-VLAN routing"
    }.items():
        results.append(finding(PASS, f"{label} requirement is enabled")
                        if isinstance(services, dict) and services.get(key) is True else
                        finding(FAIL, f"{label} requirement is missing or disabled.",
                                f"Set services.{key}: true."))

    security = plan.get("security", {})
    checks = {
        "guest_to_server": ("Guest → Server", "deny"),
        "guest_to_management": ("Guest → Management", "deny"),
        "guest_to_employee": ("Guest → Employee", "deny"),
        "management_ssh": ("Management host → SSH", "allow"),
    }
    for key, (label, expected_value) in checks.items():
        actual = str(security.get(key, "")).lower() if isinstance(security, dict) else ""
        results.append(finding(PASS, f"{label} = {expected_value.upper()}")
                        if actual == expected_value else
                        finding(FAIL, f"{label} = {actual or '<missing>'}; expected {expected_value.upper()}.",
                                f"Set security.{key}: {expected_value}."))
    return results


def check_vlan(text):
    results = []
    for vid, name in {"10": "EMPLOYEE", "20": "GUEST", "30": "SERVER", "99": "MANAGEMENT"}.items():
        if re.search(rf"(?m)^\s*{vid}\s+{name}\s+active\b", text, re.I):
            results.append(finding(PASS, f"show vlan brief: VLAN {vid} {name} exists"))
        else:
            results.append(finding(FAIL, f"show vlan brief: VLAN {vid} {name} was not found.",
                                  f"Create VLAN {vid} named {name}."))
    return results


def expand_vlan_tokens(value):
    nums = set()
    for token in re.split(r"[,\s]+", value.strip()):
        if not token:
            continue
        if "-" in token:
            try:
                a, b = token.split("-", 1)
                nums.update(range(int(a), int(b) + 1))
            except ValueError:
                pass
        elif token.isdigit():
            nums.add(int(token))
    return nums


def check_trunk(text):
    results = []
    # Find the text after the exact Cisco heading. This handles Packet Tracer
    # output where the Fa0/1 line follows the heading.
    m = re.search(
        r"Vlans allowed on trunk\s*\n(?P<body>.*?)(?:\n\s*Port\s+Vlans allowed and active|\Z)",
        text, re.I | re.S)
    body = m.group("body") if m else ""

    # Look for a line containing a port followed by the VLAN list.
    lists = re.findall(r"(?m)^\s*\S+\s+((?:\d+(?:-\d+)?)(?:,\d+(?:-\d+)?)*)\s*$", body)
    allowed = set()
    for item in lists:
        allowed |= expand_vlan_tokens(item)

    if not allowed:
        # Fallback: inspect the complete text around the heading.
        m2 = re.search(r"Vlans allowed on trunk\s*(?:\n.*){0,3}", text, re.I)
        if m2:
            allowed |= expand_vlan_tokens(m2.group(0).replace("Vlans allowed on trunk", ""))

    if not allowed:
        results.append(finding(WARN, "Could not parse the VLAN list under 'Vlans allowed on trunk'.",
                               "Save the complete 'show interfaces trunk' output."))
        return results

    for vid in (10, 20, 30, 99):
        results.append(finding(PASS, f"Trunk allows VLAN {vid}")
                        if vid in allowed else
                        finding(FAIL, f"VLAN {vid} is missing from the trunk allowed list.",
                                f"Add VLAN {vid} to the trunk allowed VLAN list."))
    return results


def check_interfaces(text):
    results = []
    for ip, label in {
        "10.10.10.1": "Employee gateway",
        "10.10.20.1": "Guest gateway",
        "10.10.30.1": "Server gateway",
        "10.10.99.1": "Management gateway",
    }.items():
        results.append(finding(PASS, f"{label} {ip} appears in interface output")
                        if ip in text else
                        finding(FAIL, f"{label} {ip} was not found.",
                                "Check router sub-interface addressing."))
    return results


def check_acl(text):
    results = []
    patterns = [
        ("Guest → Server", r"deny\s+ip\s+10\.10\.20\.0\s+0\.0\.0\.255\s+10\.10\.30\.0\s+0\.0\.0\.255"),
        ("Guest → Management", r"deny\s+ip\s+10\.10\.20\.0\s+0\.0\.0\.255\s+10\.10\.99\.0\s+0\.0\.0\.255"),
        ("Guest → Employee", r"deny\s+ip\s+10\.10\.20\.0\s+0\.0\.0\.255\s+10\.10\.10\.0\s+0\.0\.0\.255"),
        ("Guest → any", r"permit\s+ip\s+10\.10\.20\.0\s+0\.0\.0\.255\s+any"),
    ]
    for label, pattern in patterns:
        results.append(finding(PASS, f"ACL: {label} rule found")
                        if re.search(pattern, text, re.I) else
                        finding(FAIL, f"ACL: {label} rule is missing.",
                                "Review the GUEST_RESTRICT ACL."))
    return results

def check_dhcp(text):
    results = []

    for pool in ("EMPLOYEE", "GUEST", "SERVER", "MANAGEMENT"):
        pattern = rf"(?:ip\s+dhcp\s+pool\s+{pool}\b|^\s*Pool\s+{pool}\s*:)"
        
        results.append(
            finding(PASS, f"DHCP pool {pool} exists")
            if re.search(pattern, text, re.I | re.M)
            else
            finding(
                FAIL,
                f"DHCP pool {pool} is missing.",
                f"Create DHCP pool {pool}."
            )
        )

    return results


def check_ssh(text):
    results = []
    results.append(finding(PASS, "SSH version 2 is enabled")
                    if re.search(r"SSH Enabled\s*-\s*version 2\.0|ip ssh version\s+2", text, re.I)
                    else finding(FAIL, "SSH version 2 was not found.",
                                 "Configure SSH version 2."))
    results.append(finding(PASS, "VTY local authentication is configured")
                    if re.search(r"\blogin\s+local\b", text, re.I)
                    else finding(WARN, "VTY 'login local' was not found.",
                                 "Use login local for username authentication."))
    results.append(finding(PASS, "VTY transport is restricted to SSH")
                    if re.search(r"\btransport\s+input\s+ssh\b", text, re.I)
                    else finding(WARN, "VTY 'transport input ssh' was not found.",
                                 "Restrict VTY lines to SSH."))
    return results


def validate_show_outputs(show_dir):
    results = []
    for path in sorted(show_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        print(f"\n--- Checking {path.name} ---")
        name = path.name.lower()
        if "vlan" in name:
            results += check_vlan(text)
        if "trunk" in name:
            results += check_trunk(text)
        if "interface" in name:
            results += check_interfaces(text)
        if "acl" in name or "access" in name:
            results += check_acl(text)
        if "dhcp" in name:
            results += check_dhcp(text)
        if "ssh" in name:
            results += check_ssh(text)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="SmartBranch_Requirements.yaml")
    parser.add_argument("--show-dir", default=None)
    args = parser.parse_args()

    print("=" * 60)
    print("SMARTBRANCH 360 - PYTHON CONFIGURATION CHECKER")
    print("=" * 60)

    results = []
    print("\n--- Checking requirements plan ---")
    results += validate_plan(load_yaml(Path(args.plan)))
    for item in results:
        print_finding(item)

    if args.show_dir:
        results += validate_show_outputs(Path(args.show_dir))

    counts = {PASS: 0, WARN: 0, FAIL: 0}
    for item in results:
        counts[item["status"]] += 1

    print("\n" + "=" * 60)
    print("SMARTBRANCH 360 VALIDATION SUMMARY")
    print("=" * 60)
    print(f"PASS : {counts[PASS]}")
    print(f"WARN : {counts[WARN]}")
    print(f"FAIL : {counts[FAIL]}")

    if counts[FAIL] == 0:
        print("\nOverall result: PASS")
        print("No required configuration checks failed.")
        return 0

    print("\nOverall result: FAIL")
    print("Review the failed findings and apply the suggested fixes.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
