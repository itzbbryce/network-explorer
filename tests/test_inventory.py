import unittest
from unittest.mock import patch
import subprocess
from inventory import assemble, mac, run

IFACES = '''lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
 inet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,RUNNING,MULTICAST> mtu 1500
 ether d6:5f:d0:f4:71:45
 inet 192.168.1.162 netmask 0xffffff00 broadcast 192.168.1.255
 inet6 fe80::123%en0 prefixlen 64
 status: active
en3: flags=8863<UP,BROADCAST,RUNNING,MULTICAST> mtu 1500
 ether aa:bb:cc:dd:ee:ff
 inet 10.0.0.10 netmask 0xffffff00
 status: inactive
'''
ARP = '''? (192.168.1.1) at 4:b3:c9:a7:2d:c0 on en0 ifscope [ethernet]
? (192.168.1.153) at a:35:a7:35:13:85 on en0 ifscope [ethernet]
? (192.168.1.162) at d6:5f:d0:f4:71:45 on en0 ifscope permanent [ethernet]
? (192.168.1.200) at (incomplete) on en0
? (192.168.1.255) at ff:ff:ff:ff:ff:ff on en0
? (224.0.0.251) at 1:0:5e:0:0:fb on en0
? (10.0.0.2) at 12:34:56:78:9a:bc on en0
? (10.0.0.3) at 12:34:56:78:9a:be on en3
'''
NDP = '''Neighbor Linklayer Address Netif Expire St Flgs Prbs
fe80::987%en0 a:35:a7:35:13:85 en0 13s R
2001:db8::25 a:35:a7:35:13:85 en0 5s S
fe80::123%en0 d6:5f:d0:f4:71:45 en0 permanent R
fe80::456%en0 (incomplete) en0 expired N
'''
ROUTE = '    gateway: 192.168.1.1\n  interface: en0\n'

class InventoryTests(unittest.TestCase):
    def data(self, **kw):
        return assemble(dict(interfaces=IFACES, arp=ARP, ndp=NDP, route=ROUTE) | kw)
    def test_merge_v4_v6_and_exclude_non_devices(self):
        devices = self.data()['devices']
        self.assertEqual(len(devices), 3)
        self.assertEqual(devices[0]['role'], 'This Mac')
        self.assertEqual(devices[1]['role'], 'Default gateway')
        self.assertEqual(devices[2]['role'], 'Unknown device')
        self.assertEqual(len(devices[2]['addresses']), 3)
        self.assertTrue(devices[2]['private_mac'])
    def test_common_phone_ip_never_implies_phone(self):
        for ip in ['192.168.1.2', '192.168.1.100', '192.168.1.153']:
            data = self.data(arp=f'? ({ip}) at a:35:a7:35:13:85 on en0', ndp='')
            self.assertEqual(data['devices'][1]['role'], 'Unknown device')
    def test_gateway_requires_route_not_dot_one_guess(self):
        data = self.data(route='')
        self.assertNotIn('Default gateway', [d['role'] for d in data['devices']])
    def test_fail_closed_without_interfaces(self):
        self.assertEqual(self.data(interfaces='')['devices'], [])
    def test_same_mac_on_two_interfaces_not_conflated(self):
        other = IFACES + '\nen5: flags=8863<UP,BROADCAST,RUNNING> mtu 1500\n ether 12:22:33:44:55:66\n inet 10.0.0.5 netmask 0xffffff00\n status: active\n'
        d = self.data(interfaces=other, arp=ARP+'\n? (10.0.0.7) at a:35:a7:35:13:85 on en5')
        matches = [x for x in d['devices'] if x['mac']=='0a:35:a7:35:13:85']
        self.assertEqual(len(matches), 2)
        self.assertNotEqual(matches[0]['label_key'], matches[1]['label_key'])
    def test_gateway_changes_invalidate_saved_label_scope(self):
        a=self.data()['devices'][-1]['label_key']
        b=self.data(arp=ARP.replace('4:b3:c9:a7:2d:c0', '6:b3:c9:a7:2d:c0'))['devices'][-1]['label_key']
        self.assertNotEqual(a,b)
    def test_normalize_and_filter_hardware_addresses(self):
        self.assertEqual(mac('a:1:2:3:4:5'), '0a:01:02:03:04:05')
        for bad in ['ff:ff:ff:ff:ff:ff','0:0:0:0:0:0','(incomplete)','1:0:5e:0:0:fb']:
            self.assertIsNone(mac(bad))
    @patch('inventory.subprocess.run')
    def test_collection_has_no_shell_and_bounded_timeout(self, mock):
        mock.return_value = subprocess.CompletedProcess([], 0, 'data', '')
        self.assertEqual(run('arp'), ('data',''))
        args, kw = mock.call_args
        self.assertEqual(args[0], ['/usr/sbin/arp','-an'])
        self.assertEqual(kw['timeout'],6)
        self.assertFalse(kw.get('shell',False))
    @patch('inventory.subprocess.run', side_effect=subprocess.TimeoutExpired('arp',6))
    def test_timeout_becomes_visible_error(self, _):
        output,error = run('arp')
        self.assertEqual(output,'')
        self.assertTrue(error)

if __name__=='__main__': unittest.main()
