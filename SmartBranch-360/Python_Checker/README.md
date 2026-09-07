# SmartBranch 360 Python Checker

## 1. What this tool does

This checker validates the SmartBranch 360 requirements and can also inspect
Cisco IOS show-command output saved as `.txt` files.

It checks:

- VLAN 10 EMPLOYEE
- VLAN 20 GUEST
- VLAN 30 SERVER
- VLAN 99 MANAGEMENT
- VLAN subnets
- VLAN gateways
- DHCP
- DNS
- NAT
- Inter-VLAN routing
- Guest isolation
- Management SSH requirement

When show outputs are supplied, it can additionally inspect:

- `show vlan brief`
- `show interfaces trunk`
- `show ip interface brief`
- `show access-lists`
- DHCP configuration
- SSH/VTY configuration

## 2. Install Python

Check:

```bash
python3 --version
```

## 3. Install the only external package

```bash
python3 -m pip install pyyaml
```

## 4. Run the requirements check

From this folder:

```bash
python3 SmartBranch_Python_Checker.py
```

Expected ending:

```text
============================================================
SMARTBRANCH 360 VALIDATION SUMMARY
============================================================
...
Overall result: PASS
No required configuration checks failed.
```

## 5. Run against Cisco show outputs

The sample show outputs are already included:

```bash
python3 SmartBranch_Python_Checker.py \
  --plan SmartBranch_Requirements.yaml \
  --show-dir sample_show_outputs
```

## 6. Use your own Cisco output

On a router or switch, copy the relevant command output into text files.

Recommended files:

```text
show_vlan_brief.txt
show_trunk.txt
show_interfaces.txt
show_acl.txt
show_dhcp.txt
show_ssh.txt
```

Put them in a folder, for example:

```text
my_show_outputs/
```

Then run:

```bash
python3 SmartBranch_Python_Checker.py \
  --plan SmartBranch_Requirements.yaml \
  --show-dir my_show_outputs
```

## 7. Example fault demonstration

For the internship demo, create a fault such as removing VLAN 20 from a trunk.

Before the fault:

```text
Fa0/1       10,20,30,99
```

After the fault:

```text
Fa0/1       10,30,99
```

Run the checker. It should report:

```text
[FAIL] VLAN 20 is missing from the trunk allowed list.
        Suggested fix: Add VLAN 20 to the trunk allowed VLAN list.
```

Fix the trunk in Packet Tracer, save the new `show interfaces trunk`
output, and run the checker again.

The final result should be:

```text
Overall result: PASS
```

## 8. Important limitation

The checker does not connect directly to Packet Tracer. You export/copy
Cisco `show` output into text files and the Python program analyzes those
files. This keeps the project simple and demonstrates configuration
assurance without requiring a live network API.
