import asyncio
import logging
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import config
from ..db import db
from ..keyboards import DANGER, PRIMARY, SUCCESS, admin_back, admin_home, b, kb
from ..utils import esc, human_size

log = logging.getLogger("admin")
router = Router()
START = time.time()
ADMIN = F.from_user.id.in_(config.ADMIN_IDS)
PAGE = 8


class St(StatesGroup):
    find = State()
    broadcast = State()


async def maint():
    return (await db.get_kv("maintenance", "0")) == "1"


async def home_text():
    up = int(time.time() - START)
    return (f"🛠 <b>پنل مدیریت ارباب</b>\n\n⏱ آپتایم: {up // 3600}h {up % 3600 // 60}m\n"
            f"👥 کاربران: <b>{await db.count_users()}</b>")


async def edit(c: CallbackQuery, text, markup):
    try:
        await c.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


@router.message(Command("admin"), ADMIN, F.chat.type == "private")
async def cmd_admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(await home_text(), reply_markup=admin_home(await maint()))


@router.callback_query(F.data == "ad:home", ADMIN)
async def cb_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await edit(c, await home_text(), admin_home(await maint()))


@router.callback_query(F.data == "ad:stats", ADMIN)
async def cb_stats(c: CallbackQuery):
    s = await db.stats()
    def line(n, t):
        ok, bad, by = s[t]
        return f"{n}: <b>{ok}</b> موفق / {bad} ناموفق • {human_size(by)}"
    plat = "\n".join(f"  • {esc(p)}: {n}" for p, n in s["platforms"]) or "  —"
    total = s["all"][0] + s["all"][1]
    rate = f"{s['all'][0] / total * 100:.0f}%" if total else "—"
    txt = (f"📊 <b>آمار کلی</b>\n\n"
           f"👥 کاربران: <b>{s['users']}</b>  (امروز جدید: {s['users_today']} • فعال امروز: {s['active_today']})\n"
           f"🚫 مسدود: {s['banned']}   👨‍👩‍👧 گروه‌ها: {s['groups']}\n\n"
           f"{line('📥 امروز', 'today')}\n{line('📆 ۷ روز', 'week')}\n{line('🗂 کل', 'all')}\n"
           f"✅ نرخ موفقیت: {rate}\n\n🌐 <b>پلتفرم‌ها</b>\n{plat}")
    await c.answer()
    await edit(c, txt, admin_back())


@router.callback_query(F.data == "ad:usage", ADMIN)
async def cb_usage(c: CallbackQuery):
    d = await db.daily(7)
    rows = "\n".join(f"<code>{k}</code>  {v[0]:>4} دانلود  •  {human_size(v[1])}" for k, v in d.items())
    tot = sum(v[1] for v in d.values())
    await c.answer()
    await edit(c, f"📈 <b>مصرف ۷ روز اخیر</b>\n\n{rows}\n\n💾 مجموع: <b>{human_size(tot)}</b>", admin_back())


@router.callback_query(F.data == "ad:top", ADMIN)
async def cb_top(c: CallbackQuery):
    rows = await db.top_users(10)
    txt = "\n".join(f"{i}. {esc(r['first_name'] or '-')} "
                    f"({'@' + r['username'] if r['username'] else r['id']}) — {r['downloads']} • {human_size(r['bytes'])}"
                    for i, r in enumerate(rows, 1)) or "هنوز دانلودی ثبت نشده."
    await c.answer()
    await edit(c, f"🏆 <b>پرمصرف‌ترین کاربران</b>\n\n{txt}", admin_back())


@router.callback_query(F.data.startswith("ad:users:"), ADMIN)
async def cb_users(c: CallbackQuery):
    page = int(c.data.split(":")[2])
    total = await db.count_users()
    rows = await db.list_users(page * PAGE, PAGE)
    txt = f"👥 <b>کاربران</b> ({total})\n\n" + "\n".join(
        f"{'🚫' if r['banned'] else '•'} <code>{r['id']}</code> {esc(r['first_name'] or '-')} "
        f"{'@' + r['username'] if r['username'] else ''} — {r['downloads']}" for r in rows)
    btns = [[b(f"👤 {r['first_name'] or r['id']}"[:30], f"ad:user:{r['id']}", style=PRIMARY)] for r in rows]
    nav = []
    if page > 0:
        nav.append(b("◀️ قبلی", f"ad:users:{page - 1}", style=PRIMARY))
    if (page + 1) * PAGE < total:
        nav.append(b("بعدی ▶️", f"ad:users:{page + 1}", style=PRIMARY))
    if nav:
        btns.append(nav)
    btns.append([b("🔙 بازگشت", "ad:home", style=PRIMARY)])
    await c.answer()
    await edit(c, txt, kb(btns))


async def user_card(uid):
    r = await db.get_user(uid)
    if not r:
        return None, None
    joined = time.strftime("%Y-%m-%d", time.localtime(r["joined_at"]))
    seen = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["last_seen"]))
    txt = (f"👤 <b>{esc(r['first_name'] or '-')}</b> {'@' + r['username'] if r['username'] else ''}\n"
           f"🆔 <code>{r['id']}</code>\n📅 عضویت: {joined}\n🕒 آخرین فعالیت: {seen}\n"
           f"📥 دانلود: <b>{r['downloads']}</b> • 💾 {human_size(r['bytes'])}\n"
           f"وضعیت: {'🚫 مسدود' if r['banned'] else '✅ فعال'}")
    btn = (b("✅ رفع مسدودی", f"ad:unban:{uid}", style=SUCCESS) if r["banned"]
           else b("🚫 مسدود کردن", f"ad:ban:{uid}", style=DANGER))
    return txt, kb([[btn], [b("🔙 بازگشت", "ad:home", style=PRIMARY)]])


@router.callback_query(F.data.startswith("ad:user:"), ADMIN)
async def cb_user(c: CallbackQuery):
    txt, mk = await user_card(int(c.data.split(":")[2]))
    await c.answer()
    await edit(c, txt or "کاربر پیدا نشد.", mk or admin_back())


@router.callback_query(F.data.regexp(r"^ad:(ban|unban):"), ADMIN)
async def cb_ban(c: CallbackQuery):
    _, act, uid = c.data.split(":")
    uid = int(uid)
    if uid in config.ADMIN_IDS:
        await c.answer("ادمین رو نمیشه مسدود کرد", show_alert=True)
        return
    await db.set_ban(uid, act == "ban")
    from ..middleware import invalidate
    invalidate(uid)
    txt, mk = await user_card(uid)
    await c.answer("انجام شد ✅")
    await edit(c, txt, mk)


@router.callback_query(F.data == "ad:maint", ADMIN)
async def cb_maint(c: CallbackQuery):
    new = "0" if await maint() else "1"
    await db.set_kv("maintenance", new)
    await c.answer("حالت تعمیر " + ("روشن شد" if new == "1" else "خاموش شد"))
    await edit(c, await home_text(), admin_home(new == "1"))


# ---------- find user ----------
@router.callback_query(F.data == "ad:find", ADMIN)
async def cb_find(c: CallbackQuery, state: FSMContext):
    await state.set_state(St.find)
    await c.answer()
    await edit(c, "🔎 آیدی عددی یا یوزرنیم کاربر رو بفرست:", admin_back())


@router.message(St.find, ADMIN, F.chat.type == "private")
async def got_find(m: Message, state: FSMContext):
    txt, mk = await user_card(m.text or "")
    if not txt:
        await m.answer("❌ کاربر پیدا نشد. دوباره بفرست یا /admin بزن.")
        return
    await state.clear()
    await m.answer(txt, reply_markup=mk)


# ---------- broadcast ----------
@router.callback_query(F.data == "ad:bc", ADMIN)
async def cb_bc(c: CallbackQuery, state: FSMContext):
    await state.set_state(St.broadcast)
    await c.answer()
    await edit(c, "📢 پیامی که می‌خوای برای همه ارسال بشه رو بفرست (متن/عکس/ویدیو):", admin_back())


@router.message(St.broadcast, ADMIN, F.chat.type == "private")
async def got_bc(m: Message, state: FSMContext):
    await state.update_data(src_chat=m.chat.id, src_msg=m.message_id)
    n = len(await db.all_user_ids())
    await m.reply(f"ارسال برای <b>{n}</b> کاربر؟", reply_markup=kb([[
        b("✅ ارسال", "ad:bcgo", style=SUCCESS), b("❌ لغو", "ad:home", style=DANGER)]]))


@router.callback_query(F.data == "ad:bcgo", ADMIN)
async def cb_bcgo(c: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data()
    await state.clear()
    if not d.get("src_msg"):
        await c.answer("منقضی شد", show_alert=True)
        return
    await c.answer("ارسال شروع شد")
    await c.message.edit_text("📤 ارسال همگانی شروع شد…")
    asyncio.create_task(run_broadcast(bot, c.message.chat.id, d["src_chat"], d["src_msg"]))


async def run_broadcast(bot, admin_chat, src_chat, src_msg):
    ids = await db.all_user_ids()
    ok = fail = 0
    for uid in ids:
        for attempt in (1, 2):
            try:
                await bot.copy_message(uid, src_chat, src_msg)
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except (TelegramForbiddenError, TelegramBadRequest):
                fail += 1
                break
            except Exception:
                fail += 1
                break
        await asyncio.sleep(0.05)
    try:
        await bot.send_message(admin_chat, f"✅ ارسال همگانی تموم شد\n\nموفق: {ok}\nناموفق: {fail}",
                               reply_markup=admin_back())
    except Exception:
        pass
