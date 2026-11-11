# Network Explorer — observational device inventory

Start from Terminal:

```sh
cd network-explorer
python3 app.py
```

A dedicated Mac window lists neighbors already visible in the Mac's ARP (IPv4) and NDP (IPv6) caches. It reads interface configuration and the default route to identify **This Mac** and **Default gateway**. Broadcast, multicast, incomplete records, and inactive interfaces are excluded. Multiple addresses with the same hardware address on an interface are grouped.

## Controls

- Refresh devices / Command-R: read local records again.
- Optional refresh every 15 seconds: repeats local reads while the window is open.
- Search and interface filter: narrow visible records.
- Select a row: see addresses, hardware address, and evidence.
- Your label / Save label: give an unknown device a name. Clear and save to remove a label.
- Export snapshot: save a private JSON inventory where you choose.
- Close window / Command-Q: exit; no background monitor remains.

## Honest limits

This is not a complete list of every router client, nor an online/offline test. Cached neighbors can be stale, and a device that has never been visible to the Mac may be absent. A proxy/bridge can group multiple devices behind one hardware address. Addresses don't reliably identify device types. Randomized/private hardware addresses can change; labels are scoped to an observed interface/subnet/gateway/hardware address, not a permanent identity. No vendor guesses or phone labels are made from IP ranges.

## Safety and privacy

The only collection commands are fixed read-only invocations: `ifconfig -a`, `route -n get default`, `arp -an`, `ndp -an`. No ping, DNS lookup, port scan, SSH, file-share login, packet interception, firewall/router change, telemetry, server, or AI upload. The program never requests administrator access. If a source is inaccessible it shows the error and marks the results as partial. It reads active hardware interfaces; use the filter if several are connected.

Only user labels are saved automatically in `.state/labels.json`. Exports include private addresses and should not be published. Don't commit `.state`, exports, or real network captures to GitHub.

## Requirements and learning

Uses the already-installed Python 3 with Tkinter; no third-party packages. Tested against local macOS output and synthetic fixtures. The code is split into `inventory.py` (collection/parsing) and `app.py` (window/labels). Start by changing a label, then read the filtering in `assemble()` to understand why broadcast addresses aren't devices.

Run tests: `python3 -m unittest discover -s tests -v` from this folder.

Connections, SSH/file-sharing controls, traffic graphs, and AI are deferred. This release implements the user's latest request: list observed devices only.
