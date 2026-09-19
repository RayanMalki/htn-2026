import socket

import pytest

from app.downloader import public_resolver


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "::1", "fc00::1"])
def test_downloader_blocks_private_redirect_destinations(address):
    def resolver(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    with pytest.raises(OSError):
        public_resolver(resolver)("cdn.example", 443)


def test_downloader_allows_public_resolution():
    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    assert public_resolver(lambda *args: addresses)("cdn.example", 443) == addresses
