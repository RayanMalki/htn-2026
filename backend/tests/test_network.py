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


async def test_shorts_download_uses_canonical_host_and_merges_streams(monkeypatch, tmp_path):
    from pathlib import Path

    from app.config import settings
    from app.media import download

    monkeypatch.setattr(settings(), "media_root", tmp_path)
    hosts = []

    def resolve(host, port):
        hosts.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]

    async def process(*args, timeout):
        assert timeout == 15
        assert args[-1] == "https://www.youtube.com/shorts/BGQWPY4IigY"
        assert "bestvideo" in args[args.index("-f") + 1]
        output = Path(args[args.index("-o") + 1].replace("%(ext)s", "mp4"))
        output.write_bytes(b"merged video fixture")

    monkeypatch.setattr("app.media.socket.getaddrinfo", resolve)
    monkeypatch.setattr("app.media.run_process", process)
    result = await download("shorts-test", "https://m.youtube.com/shorts/BGQWPY4IigY?si=tracking")
    assert hosts == ["www.youtube.com"]
    assert result.name == "source.mp4"
