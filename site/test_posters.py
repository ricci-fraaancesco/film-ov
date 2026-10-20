"""Tests for the poster cache (no network)."""
import io

from PIL import Image

from posters import poster_name, sync


def fake_jpeg(w=450, h=630) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 60, 90)).save(buf, "JPEG")
    return buf.getvalue()


def test_each_poster_downloaded_once(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return fake_jpeg()

    urls = {"https://cdn.18tickets.net/a.jpg", "https://cdn.18tickets.net/b.jpg"}
    cache, out = tmp_path / "cache", tmp_path / "out"
    s1 = sync(urls, cache, out, fetch=fetch, delay=0)
    s2 = sync(urls, cache, out, fetch=fetch, delay=0)
    assert s1["downloaded"] == 2 and s2["downloaded"] == 0 and s2["cached"] == 2
    assert len(calls) == 2
    stem = poster_name("https://cdn.18tickets.net/a.jpg")
    with Image.open(out / f"{stem}-s.webp") as im:
        assert im.width == 120
    with Image.open(out / f"{stem}-m.webp") as im:
        assert im.width == 450  # never upscaled


def test_only_current_posters_published(tmp_path):
    cache, out = tmp_path / "cache", tmp_path / "out"
    sync({"https://x/a.jpg", "https://x/b.jpg"}, cache, out, fetch=lambda u: fake_jpeg(), delay=0)
    sync({"https://x/a.jpg"}, cache, out, fetch=lambda u: fake_jpeg(), delay=0)
    published = {p.name.split("-")[0] for p in out.iterdir()}
    assert published == {poster_name("https://x/a.jpg")}


def test_failed_download_is_skipped(tmp_path):
    def boom(url):
        raise OSError("blocked")

    s = sync({"https://x/a.jpg"}, tmp_path / "c", tmp_path / "o", fetch=boom, delay=0)
    assert s["failed"] == 1 and not any((tmp_path / "o").iterdir())
