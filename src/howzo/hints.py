"""Curated 'when to use' hints for core tools whose man pages under-describe
what people actually reach for them for.

Plain data — extend it as you find tools that never surface for the words
users type. Hints only fill an empty when_to_use, so anything you set
yourself always wins.
"""

HINTS = {
    "ifconfig": "show or change your ip address, network interface (en0/wlan0 on macOS), mac address, dhcp",
    "ip": "show ip addresses and interfaces (Linux: ip addr)",
    "ipconfig": "show your ip address (Windows: ipconfig /all)",
    "route": "default gateway, routing table",
    "arp": "mac address behind an ip, arp table",
    "netstat": "open ports, listening sockets, network connections",
}


def apply_hints(c):
    """Fill empty when_to_use fields from HINTS; never clobbers existing values."""
    n = 0
    for name, hint in HINTS.items():
        cur = c.execute("UPDATE tools SET when_to_use=? WHERE name=? AND when_to_use=''",
                        (hint, name))
        n += cur.rowcount
    return n
