"""IPv4 LAN discovery for the explicitly enabled local-network launcher."""

import ipaddress
import socket

PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def lan_addresses():
    records = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
    addresses = {ipaddress.ip_address(record[4][0]) for record in records}
    return [
        str(address)
        for address in sorted(addresses)
        if any(address in subnet for subnet in PRIVATE_NETWORKS)
    ]


def serving_addresses(lan=False, address=None):
    if address and not lan:
        raise ValueError("--lan-address requires --lan.")
    if not lan:
        return ["127.0.0.1"]
    discovered = lan_addresses()
    if address:
        if address not in discovered:
            raise ValueError(
                "--lan-address must be one of this PC's detected private IPv4 addresses."
            )
        discovered = [address]
    if not discovered:
        raise ValueError(
            "No private LAN IPv4 address was found. Connect the PC to your home router and try again."
        )
    return ["127.0.0.1", *discovered]
