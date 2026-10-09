import html
import re
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

HOSTS = {
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "instagram.com": "Instagram", "instagr.am": "Instagram",
    "tiktok.com": "TikTok",
    "twitter.com": "X", "x.com": "X",
    "facebook.com": "Facebook", "fb.watch": "Facebook", "fb.com": "Facebook",
    "reddit.com": "Reddit", "redd.it": "Reddit",
    "pinterest.com": "Pinterest", "pin.it": "Pinterest",
    "soundcloud.com": "SoundCloud", "vimeo.com": "Vimeo",
    "twitch.tv": "Twitch", "snapchat.com": "Snapchat",
    "threads.net": "Threads", "threads.com": "Threads",
    "dailymotion.com": "Dailymotion", "bilibili.com": "Bilibili",
    "likee.video": "Likee", "ok.ru": "OK", "vk.com": "VK",
    "tumblr.com": "Tumblr", "streamable.com": "Streamable",
}

esc = html.escape


def extract_urls(text):
    out = []
    for m in URL_RE.findall(text or ""):
        m = m.rstrip(".,;:!?)]}»›")
        if m not in out:
            out.append(m)
    return out


def host_of(url):
    return (urlparse(url).hostname or "").lower()


def known_platform(url):
    h = host_of(url)
    for dom, name in HOSTS.items():
        if h == dom or h.endswith("." + dom):
            return name
    return None


def platform_of(url):
    return known_platform(url) or (host_of(url).removeprefix("www.") or "Other")


def human_size(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def human_dur(s):
    s = int(s or 0)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def bar(pct, n=10):
    k = max(0, min(n, int(pct / 100 * n)))
    return "▰" * k + "▱" * (n - k)
