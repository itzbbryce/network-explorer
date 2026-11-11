"""Read macOS neighbor caches. Never sends probes, resolves names, or opens sockets."""
from __future__ import annotations
import datetime as dt
import ipaddress
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

COMMANDS = {
    'interfaces': ['/sbin/ifconfig', '-a'],
    'route': ['/sbin/route', '-n', 'get', 'default'],
    'arp': ['/usr/sbin/arp', '-an'],
    'ndp': ['/usr/sbin/ndp', '-an'],
}

def run(name):
    try:
        p = subprocess.run(COMMANDS[name], capture_output=True, text=True, timeout=6,
                           env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C'})
        return p.stdout, (p.stderr.strip() or f'{name}: exit {p.returncode}') if p.returncode else ''
    except (OSError, subprocess.TimeoutExpired) as exc:
        return '', f'{name}: {exc}'

def mac(value):
    parts = value.lower().split(':')
    if len(parts) != 6 or any(not re.fullmatch('[0-9a-f]{1,2}', x) for x in parts):
        return None
    result = ':'.join(f'{int(x, 16):02x}' for x in parts)
    # Exclude multicast/broadcast and missing hardware addresses.
    return None if int(parts[0], 16) & 1 or result == '00:00:00:00:00:00' else result

def interfaces(text):
    result, current = {}, None
    for line in text.splitlines():
        match = re.match(r'^(\S+): flags=\d+<([^>]+)>', line)
        if match:
            name, flags = match.groups()
            current = {'name': name, 'up': 'UP' in flags.split(','), 'loopback': 'LOOPBACK' in flags,
                       'ips': [], 'networks': [], 'mac': None, 'active': True}
            result[name] = current
        elif current is not None:
            words = line.split()
            if words[:1] == ['ether']:
                current['mac'] = mac(words[1])
            elif words[:1] == ['status:']:
                current['active'] = words[1] == 'active'
            elif words[:1] == ['inet']:
                try:
                    address = ipaddress.IPv4Address(words[1])
                    maskstr = words[words.index('netmask') + 1]
                    maskstr = str(ipaddress.IPv4Address(int(maskstr, 16))) if maskstr.startswith('0x') else maskstr
                    net = ipaddress.IPv4Network(f'{address}/{maskstr}', strict=False)
                    current['ips'].append(str(address))
                    current['networks'].append(str(net))
                except (ValueError, IndexError):
                    pass
            elif words[:1] == ['inet6']:
                try:
                    address = ipaddress.IPv6Address(words[1].split('%')[0])
                    current['ips'].append(str(address))
                except (ValueError, IndexError):
                    pass
    return {k: v for k, v in result.items()
            if v['up'] and v['active'] and not v['loopback'] and v['mac'] and v['ips']}

def route(text):
    return dict(re.findall(r'^\s*(gateway|interface):\s*(\S+)', text, re.M))

def neighbors(arp, ndp):
    rows = []
    for line in arp.splitlines():
        m = re.match(r'.*?\(([^)]+)\) at (\S+) on (\S+)', line)
        if m and mac(m[2]):
            rows.append({'ip': m[1], 'mac': mac(m[2]), 'interface': m[3], 'source': 'IPv4 neighbor cache (ARP)'})
    for line in ndp.splitlines():
        parts = line.split()
        if len(parts) >= 3 and mac(parts[1]):
            try:
                ipaddress.IPv6Address(parts[0].split('%')[0])
            except ValueError:
                continue
            rows.append({'ip': parts[0], 'mac': mac(parts[1]), 'interface': parts[2], 'source': 'IPv6 neighbor cache (NDP)'})
    return rows

def assemble(outputs, errors=None):
    nets = interfaces(outputs.get('interfaces', ''))
    routing = route(outputs.get('route', ''))
    rows = neighbors(outputs.get('arp', ''), outputs.get('ndp', ''))
    groups = {}
    def add(iface, hw, addr, source, role='Unknown device'):
        key = f'{iface}|{hw}'
        if key not in groups:
            groups[key] = {'id': key, 'interface': iface, 'mac': hw, 'addresses': [], 'sources': [], 'role': role}
        g = groups[key]
        if addr not in g['addresses']: g['addresses'].append(addr)
        if source not in g['sources']: g['sources'].append(source)
        if role != 'Unknown device': g['role'] = role
    for name, iface in nets.items():
        for addr in iface['ips']: add(name, iface['mac'], addr, 'Mac interface configuration', 'This Mac')
    for row in rows:
        iface = nets.get(row['interface'])
        if not iface: continue
        try:
            ip = ipaddress.ip_address(row['ip'].split('%')[0])
        except ValueError:
            continue
        if ip.is_multicast or ip.is_unspecified or ip.is_loopback: continue
        if ip.version == 4:
            scope = [ipaddress.ip_network(n) for n in iface['networks']]
            if not any(ip in n and ip not in (n.broadcast_address, n.network_address) for n in scope): continue
        role = 'Unknown device'
        if row['mac'] == iface['mac']: role = 'This Mac'
        elif row['ip'] == routing.get('gateway') and row['interface'] == routing.get('interface'):
            role = 'Default gateway'
        add(row['interface'], row['mac'], row['ip'], row['source'], role)
    for item in groups.values():
        iface = nets[item['interface']]
        gateway = next((r['mac'] for r in rows if r['ip'] == routing.get('gateway')
                        and r['interface'] == item['interface']), 'unknown-gateway')
        item['label_key'] = '|'.join([item['interface'], ','.join(sorted(iface['networks'])), gateway, item['mac']])
        item['addresses'].sort(key=lambda a: (':' in a, int(ipaddress.ip_address(a.split('%')[0]))))
        item['private_mac'] = bool(int(item['mac'].split(':')[0], 16) & 2)
    devices = sorted(groups.values(), key=lambda d: (d['role'] != 'This Mac', d['role'] != 'Default gateway', d['addresses'][0]))
    return {'observed_at': dt.datetime.now().astimezone().isoformat(timespec='seconds'),
            'interfaces': nets, 'route': routing, 'devices': devices, 'errors': errors or {},
            'method': 'Read-only local ARP/NDP caches and interface configuration. No probes or connections.',
            'limitation': 'Cached neighbors are not verified online. This is not a complete router client list. Multiple IPs sharing a MAC are grouped as one observed neighbor; proxies may aggregate devices.'}

def collect():
    with ThreadPoolExecutor(max_workers=4) as pool:
        pairs = dict(zip(COMMANDS, pool.map(run, COMMANDS)))
    return assemble({k: v[0] for k, v in pairs.items()}, {k: v[1] for k, v in pairs.items() if v[1]})
