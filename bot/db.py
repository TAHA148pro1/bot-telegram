import time
from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite

from . import config

TZ = ZoneInfo(config.TZ_NAME)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
  joined_at INTEGER, last_seen INTEGER,
  banned INTEGER DEFAULT 0, downloads INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS chats(
  id INTEGER PRIMARY KEY, title TEXT, type TEXT, added_at INTEGER, last_seen INTEGER);
CREATE TABLE IF NOT EXISTS downloads(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, chat_type TEXT,
  url TEXT, platform TEXT, quality TEXT, status TEXT, size INTEGER DEFAULT 0,
  secs REAL DEFAULT 0, error TEXT, ts INTEGER);
CREATE INDEX IF NOT EXISTS ix_dl_ts ON downloads(ts);
CREATE INDEX IF NOT EXISTS ix_dl_user ON downloads(user_id, ts);
CREATE TABLE IF NOT EXISTS file_cache(key TEXT PRIMARY KEY, file_id TEXT, kind TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
"""


def day_start(offset_days=0):
    now = datetime.now(TZ)
    d = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp()) - offset_days * 86400


class DB:
    def __init__(self, path):
        self.path = str(path)
        self.c = None

    async def connect(self):
        self.c = await aiosqlite.connect(self.path, timeout=30)
        self.c.row_factory = aiosqlite.Row
        await self.c.execute("PRAGMA journal_mode=WAL")
        await self.c.execute("PRAGMA synchronous=NORMAL")
        await self.c.executescript(SCHEMA)
        await self.c.commit()

    async def close(self):
        if self.c:
            await self.c.close()

    async def q(self, sql, args=()):
        cur = await self.c.execute(sql, args)
        rows = await cur.fetchall()
        await cur.close()
        return rows

    async def one(self, sql, args=()):
        r = await self.q(sql, args)
        return r[0] if r else None

    async def x(self, sql, args=()):
        await self.c.execute(sql, args)
        await self.c.commit()

    # ---------- users / chats ----------
    async def touch_user(self, u):
        now = int(time.time())
        await self.x(
            "INSERT INTO users(id,username,first_name,joined_at,last_seen) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET username=excluded.username, "
            "first_name=excluded.first_name, last_seen=excluded.last_seen",
            (u.id, u.username, u.first_name, now, now))
        r = await self.one("SELECT banned FROM users WHERE id=?", (u.id,))
        return bool(r["banned"]) if r else False

    async def touch_chat(self, c):
        now = int(time.time())
        await self.x(
            "INSERT INTO chats(id,title,type,added_at,last_seen) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, last_seen=excluded.last_seen",
            (c.id, c.title, c.type, now, now))

    async def set_ban(self, uid, v):
        await self.x("UPDATE users SET banned=? WHERE id=?", (1 if v else 0, uid))

    async def get_user(self, key):
        key = str(key).strip().lstrip("@")
        if key.lstrip("-").isdigit():
            return await self.one("SELECT * FROM users WHERE id=?", (int(key),))
        return await self.one("SELECT * FROM users WHERE lower(username)=lower(?)", (key,))

    async def list_users(self, offset, limit):
        return await self.q("SELECT * FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?", (limit, offset))

    async def all_user_ids(self):
        return [r["id"] for r in await self.q("SELECT id FROM users WHERE banned=0")]

    # ---------- downloads ----------
    async def add_download(self, user_id, chat_id, chat_type, url, platform, quality, status, size, secs, error=""):
        await self.x(
            "INSERT INTO downloads(user_id,chat_id,chat_type,url,platform,quality,status,size,secs,error,ts) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, chat_id, chat_type, url[:500], platform, quality, status, size, secs, (error or "")[:300],
             int(time.time())))
        if status == "ok":
            await self.x("UPDATE users SET downloads=downloads+1, bytes=bytes+? WHERE id=?", (size, user_id))

    async def user_today_count(self, uid):
        r = await self.one("SELECT COUNT(*) n FROM downloads WHERE user_id=? AND status='ok' AND ts>=?",
                           (uid, day_start()))
        return r["n"]

    async def get_file(self, key):
        r = await self.one("SELECT file_id, kind FROM file_cache WHERE key=?", (key,))
        return (r["file_id"], r["kind"]) if r else None

    async def put_file(self, key, file_id, kind):
        await self.x("INSERT OR REPLACE INTO file_cache(key,file_id,kind,ts) VALUES(?,?,?,?)",
                     (key, file_id, kind, int(time.time())))

    # ---------- kv ----------
    async def get_kv(self, k, default=""):
        r = await self.one("SELECT value FROM kv WHERE key=?", (k,))
        return r["value"] if r else default

    async def set_kv(self, k, v):
        await self.x("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (k, str(v)))

    # ---------- stats ----------
    async def stats(self):
        t0, w0 = day_start(), day_start(6)
        s = {}
        s["users"] = (await self.one("SELECT COUNT(*) n FROM users"))["n"]
        s["users_today"] = (await self.one("SELECT COUNT(*) n FROM users WHERE joined_at>=?", (t0,)))["n"]
        s["active_today"] = (await self.one("SELECT COUNT(*) n FROM users WHERE last_seen>=?", (t0,)))["n"]
        s["banned"] = (await self.one("SELECT COUNT(*) n FROM users WHERE banned=1"))["n"]
        s["groups"] = (await self.one("SELECT COUNT(*) n FROM chats WHERE type IN ('group','supergroup')"))["n"]
        for name, since in (("all", 0), ("today", t0), ("week", w0)):
            r = await self.one(
                "SELECT SUM(status='ok') ok, SUM(status!='ok') bad, COALESCE(SUM(CASE WHEN status='ok' THEN size END),0) b "
                "FROM downloads WHERE ts>=?", (since,))
            s[name] = (r["ok"] or 0, r["bad"] or 0, r["b"] or 0)
        s["platforms"] = [(r["platform"], r["n"]) for r in await self.q(
            "SELECT platform, COUNT(*) n FROM downloads WHERE status='ok' GROUP BY platform ORDER BY n DESC LIMIT 8")]
        return s

    async def daily(self, days=7):
        rows = await self.q("SELECT ts,size,status FROM downloads WHERE ts>=?", (day_start(days - 1),))
        buckets = {}
        for i in range(days):
            d = datetime.fromtimestamp(day_start(days - 1 - i), TZ).strftime("%m/%d")
            buckets[d] = [0, 0]
        for r in rows:
            if r["status"] != "ok":
                continue
            d = datetime.fromtimestamp(r["ts"], TZ).strftime("%m/%d")
            if d in buckets:
                buckets[d][0] += 1
                buckets[d][1] += r["size"] or 0
        return buckets

    async def top_users(self, limit=10):
        return await self.q("SELECT * FROM users WHERE downloads>0 ORDER BY bytes DESC LIMIT ?", (limit,))

    async def count_users(self):
        return (await self.one("SELECT COUNT(*) n FROM users"))["n"]


db = DB(config.DATA_DIR / "bot.sqlite3")
