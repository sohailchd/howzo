"""Curated 'when to use' hints for core tools whose man pages under-describe
what people actually reach for them for.

Plain data — extend it as you find tools that never surface for the words
users type. Hints only fill an empty when_to_use, so anything you set
yourself always wins.
"""
from . import config

HINTS = {
    "ifconfig": "find or change your ip address, network interface (en0/wlan0 on macOS), mac address, dhcp",
    "grep": "search for lines that match a pattern in file contents, command output, or log files",
    "find": "search the file system for files by name, size, or age and act on them",
    "df": "check disk space, free space on a volume, how full the disk is",
    "ps": "list running processes, what is running, cpu and memory usage of a process",
    "top": "watch running processes live, cpu and memory usage, find a runaway process",
    "du": "how much space a directory or file takes, disk usage of a folder",
    "kill": "stop or terminate a process, send a signal to a process",
    "sips": "convert, resize, rotate, or crop an image file; export an image to pdf (macOS)",
    "curl": "download files from the web, make http requests, transfer a url",
    "jq": "query, filter, and transform json documents; parse api responses",
    "head": "show the first lines of a file, preview the beginning of a file",
    "tail": "show the last lines of a file, follow a log file as it grows",
    "wc": "count lines, words, and bytes in a file",
    "ssh": "connect to a remote server, run commands over ssh, secure copy with scp",
    "ip": "show ip addresses and interfaces (Linux: ip addr)",
    "ipconfig": "show your ip address (Windows: ipconfig /all)",
    "route": "default gateway, routing table",
    "arp": "mac address behind an ip, arp table",
    "netstat": "open ports, listening sockets, network connections",
}


def apply_hints(c):
    """Fill empty when_to_use fields from HINTS; never clobbers existing values.

    'ipconfig' is only hinted on Windows: there it IS the 'show my ip
    address' tool. On macOS/Linux the same name is a low-level
    IPConfiguration agent tool, and hinting it would pull the wrong tool
    up for 'ip address' queries (ifconfig is the right one there)."""
    n = 0
    for name, hint in HINTS.items():
        if name == "ipconfig" and not config.IS_WINDOWS:
            continue
        cur = c.execute("UPDATE tools SET when_to_use=? WHERE name=? AND when_to_use=''",
                        (hint, name))
        n += cur.rowcount
    return n
