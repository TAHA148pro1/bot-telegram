import logging
import re
from dataclasses import dataclass
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadCancelled, match_filter_func

from . import config

log = logging.getLogger("dl")

IMG = {".jpg", ".jpeg", ".png", ".webp"}
AUD = {".mp3", ".m4a", ".opus", ".ogg", ".aac"}
SKIP = {".part", ".ytdl", ".json", ".vtt", ".srt", ".temp"}
TIERS = [1080, 720, 480, 360, 240]


class DlError(Exception):
    """Error with a user-friendly Persian message."""


@dataclass
class Result:
    path: Path
    title: str
    duration: int
    width: int
    height: int
    kind: str  # video | audio | photo
    size: int


def _base():
    o = {
        "quiet": True, "no_warnings": True, "noplaylist": True, "playlist_items": "1",
        "socket_timeout": 25, "retries": 3, "fragment_retries": 3, "extractor_retries": 2,
        "concurrent_fragment_downloads": 4, "geo_bypass": True, "restrictfilenames": True,
        "js_runtimes": {"node": {}},
    }
    if config.COOKIES_FILE:
        o["cookiefile"] = config.COOKIES_FILE
    if config.PROXY:
        o["proxy"] = config.PROXY
    return o


def _first(info):
    if info and info.get("entries"):
        for e in info["entries"]:
            if e:
                return e
    return info


def fetch_info(url):
    with YoutubeDL({**_base(), "skip_download": True}) as y:
        return _first(y.extract_info(url, download=False))


def selector(q):
    if q == "a":
        return "bestaudio[ext=m4a]/bestaudio/best"
    if q == "b":
        return "b[ext=mp4]/bv*+ba/b"
    h = int(q)
    return (f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/"
            f"b[height<={h}][ext=mp4]/b[height<={h}]/b")


def _fsize(f):
    return f.get("filesize") or f.get("filesize_approx") or 0


def quality_options(info):
    """-> (has_video, [(q, size_estimate)])"""
    fmts = info.get("formats") or []
    vids = [f for f in fmts if f.get("vcodec") not in (None, "none") and f.get("height")]
    if not vids:
        has_v = bool(fmts) and any(f.get("vcodec") not in (None, "none") for f in fmts)
        return has_v, ([("b", 0)] if has_v else [])
    mh = max(f["height"] for f in vids)
    heights = [t for t in TIERS if t <= mh]
    if mh < 1080 and mh not in heights:
        heights.insert(0, mh)
    if not heights:
        heights = [mh]
    audio = max([_fsize(f) for f in fmts if f.get("vcodec") == "none" and f.get("acodec") != "none"] or [0])
    dur = info.get("duration") or 0
    out, seen = [], set()
    for h in heights:
        c = [f for f in vids if f["height"] <= h]
        if not c:
            continue
        best = max(c, key=lambda f: (f["height"], f.get("tbr") or 0))
        if best["height"] in seen:
            continue
        seen.add(best["height"])
        size = _fsize(best)
        if not size and dur and best.get("tbr"):
            size = int(best["tbr"] * 125 * dur)
        if size and best.get("acodec") in (None, "none"):
            size += audio
        out.append((str(best["height"] if best["height"] < h else h), size))
    return True, out


def fallback_chain(q):
    if q in ("a", "b"):
        return [q]
    h = int(q)
    return [q] + [str(x) for x in (720, 480, 360, 240) if x < h][:2]


def friendly_error(e):
    m = str(e).lower()
    if "sign in to confirm" in m or "confirm you" in m and "bot" in m:
        return "ببخشید ارباب، یوتیوب این درخواست رو بلاک کرد (نیاز به کوکی). بعداً دوباره امتحان کنین."
    if "private" in m:
        return "ارباب، این محتوا خصوصیه و قابل دانلود نیست."
    if "login" in m or "cookies" in m or "rate-limit" in m or "empty media response" in m:
        return "ارباب، این پلتفرم برای این لینک نیاز به ورود (کوکی) داره یا محدودیت زده."
    if "unsupported url" in m:
        return "ببخشید ارباب، این لینک پشتیبانی نمیشه."
    if "no video" in m or "there is no video" in m:
        return "ارباب، توی این لینک ویدیویی پیدا نشد."
    if "not available" in m or "unavailable" in m or "removed" in m or "deleted" in m:
        return "ارباب، این محتوا در دسترس نیست یا حذف شده."
    if "copyright" in m or "blocked" in m or "geo" in m:
        return "ارباب، این محتوا به دلیل محدودیت منطقه‌ای/کپی‌رایت در دسترس نیست."
    if "live" in m:
        return "ببخشید ارباب، لایو پشتیبانی نمیشه."
    if "timed out" in m or "timeout" in m or "connection" in m:
        return "ارباب، مشکل شبکه پیش اومد. دوباره امتحان کنین."
    return "ببخشید ارباب، دانلود ناموفق بود. لینک رو چک کنین یا کیفیت دیگه‌ای امتحان بفرمایین."


def download(url, q, outdir, prog):
    def hook(d):
        if prog.get("cancel"):
            raise DownloadCancelled("cancelled")
        if d.get("status") == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            prog["pct"] = (done / tot * 100) if tot else 0
            prog["speed"] = re.sub(r"\x1b\[[0-9;]*m", "", d.get("_speed_str") or "").strip()
        elif d.get("status") == "finished":
            prog["stage"] = "merge"

    o = _base()
    o.update({
        "format": selector(q),
        "outtmpl": str(Path(outdir) / "%(id).60B.%(ext)s"),
        "merge_output_format": "mp4",
        "progress_hooks": [hook],
        "max_filesize": config.UPLOAD_LIMIT * 3,
    })
    if config.MAX_DURATION_MIN > 0:
        o["match_filter"] = match_filter_func(f"!is_live & duration <=? {config.MAX_DURATION_MIN * 60}")
    if q == "a":
        o["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    try:
        with YoutubeDL(o) as y:
            info = _first(y.extract_info(url, download=True))
    except DownloadCancelled:
        raise
    except Exception as e:  # noqa
        log.warning("download failed %s: %s", url, e)
        raise DlError(friendly_error(e))

    files = [p for p in Path(outdir).iterdir() if p.is_file() and p.suffix.lower() not in SKIP]
    if not files:
        raise DlError("ارباب، فایلی دریافت نشد (شاید ویدیو از حد مجاز طولانی‌تره یا لایوه).")
    p = max(files, key=lambda x: x.stat().st_size)
    ext = p.suffix.lower()
    kind = "photo" if ext in IMG else "audio" if ext in AUD or q == "a" else "video"
    info = info or {}
    return Result(p, (info.get("title") or "")[:200], int(info.get("duration") or 0),
                  int(info.get("width") or 0), int(info.get("height") or 0), kind, p.stat().st_size)
