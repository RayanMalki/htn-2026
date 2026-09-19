"""Isolated yt-dlp process with public-only DNS resolution, including CDN redirects."""
import socket
import sys
from ipaddress import ip_address


def public_resolver(resolve):
    def guarded(*args, **kwargs):
        addresses = resolve(*args, **kwargs)
        if not addresses or any(not ip_address(entry[4][0]).is_global for entry in addresses):
            raise OSError("Refusing a non-public network destination")
        return addresses
    return guarded


def main():
    socket.getaddrinfo = public_resolver(socket.getaddrinfo)
    # Disable proxy environment: otherwise a proxy could resolve private destinations on our behalf.
    import yt_dlp
    yt_dlp.main(["--proxy", "", "--use-extractors", "Instagram", *sys.argv[1:]])


if __name__ == "__main__":
    main()
