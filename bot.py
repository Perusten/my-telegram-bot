#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import io
import re
import csv
import time
import html
import logging
import sqlite3
import datetime
import threading
import http.server
import socketserver
from typing import Optional

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH = os.getenv("BOT_DB", "bot.db")

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("assistant-bot")

UTC = datetime.timezone.utc

# Conversation states
ADD_TEXT, ADD_TIME = range(2)
FILE_TEXT, FILE_FORMAT = range(2, 4)

# ----------------------------------------------------------------------------
# i18n (Translations)
# ----------------------------------------------------------------------------
STRINGS = {
    "en": {
        "welcome": "👋 <b>Welcome!</b>\n\nI'm your all-in-one assistant:\n• 📝 To-do lists with custom reminders\n• 📄 Turn any text into .txt / .csv files\n• 🔄 Sync with TickTick and other apps\n• 🌍 Arabic & English\n\nUse /help to see every command.",
        "help": "<b>Commands</b>\n\n/add [text] – new task (then send the reminder time)\n/list – show your pending tasks\n/done &lt;id&gt; – mark a task as done\n/del &lt;id&gt; – delete a task\n/remind &lt;id&gt; &lt;time&gt; – set/change a reminder\n/tofile – convert text into a .txt or .csv file\n/export csv|ics|ticktick – export your tasks\n/import – send me a CSV file to import tasks\n\n<b>TickTick</b>\n/tt_setup &lt;client_id&gt; &lt;client_secret&gt; [redirect_uri]\n/tt_login – get the authorization link\n/tt_code &lt;code&gt; – finish login\n/tt_projects – choose the target list\n/tt_push – send local tasks to TickTick\n/tt_pull – import tasks from TickTick\n/tt_unlink – disconnect\n\n<b>Settings</b>\n/lang – change language\n/tz &lt;offset&gt; – timezone, e.g. /tz +3 or /tz -5.5\n/cancel – abort the current step\n\n<b>Time formats</b>\n<code>30m</code> · <code>2h30m</code> · <code>1d</code> (relative)\n<code>2025-01-30 14:30</code> (absolute)\n<code>14:30</code> (today)\nSend <code>skip</code> to save without a reminder.",
        "choose_lang": "🌍 Choose your language:",
        "lang_set": "✅ Language set to English.",
        "tz_usage": "Send the offset from UTC, e.g. <code>/tz +3</code> or <code>/tz -5.5</code>.",
        "tz_set": "✅ Timezone set to UTC{off}. Current time: {now}",
        "add_ask_text": "📝 Send me the task text:",
        "add_ask_time": "⏰ When should I remind you?\n\nExamples: <code>30m</code>, <code>2h</code>, <code>2025-01-30 14:30</code>, <code>14:30</code>\nOr send <code>skip</code>.",
        "time_bad": "❌ I couldn't understand that time. Try <code>30m</code>, <code>2h30m</code>, <code>2025-01-30 14:30</code> or <code>skip</code>.",
        "add_done": "✅ Task #{id} added.",
        "add_done_remind": "✅ Task #{id} added — I'll remind you at {when}.",
        "list_empty": "📭 Your list is empty. Use /add to create a task.",
        "list_header": "📋 <b>Your tasks</b> ({n} pending):",
        "done_usage": "Usage: <code>/done &lt;id&gt;</code>",
        "done_ok": "✅ Task #{id} marked as done.",
        "not_found": "❌ No task with that id.",
        "del_ok": "🗑 Task #{id} deleted.",
        "remind_usage": "Usage: <code>/remind &lt;id&gt; &lt;time&gt;</code>",
        "remind_set": "⏰ Reminder for task #{id} set to {when}.",
        "remind_cleared": "🔕 Reminder for task #{id} cleared.",
        "file_ask_text": "📄 Send me the text you want to convert into a file:",
        "file_ask_format": "Choose the output format:",
        "file_caption": "Here is your {fmt} file.",
        "file_empty": "❌ The text is empty.",
        "export_usage": "Usage: <code>/export csv</code>, <code>/export ics</code> or <code>/export ticktick</code>",
        "export_empty": "📭 You have no tasks to export.",
        "import_usage": "Send me a <b>.csv</b> file (one task per line, first column = task text).",
        "import_done": "✅ Imported {n} task(s).",
        "import_fail": "❌ Couldn't read that CSV file.",
        "cancelled": "❎ Cancelled.",
        "unknown": "🤔 I didn't get that. Use /help to see what I can do.",
        "reminder_msg": "🔔 <b>Reminder</b>\n\n{text}",
        "tt_help": "<b>TickTick</b>\n\n1) Create an app at developer.ticktick.com\n2) Set redirect URI to <code>http://localhost:8080/callback</code>\n3) <code>/tt_setup CLIENT_ID CLIENT_SECRET</code>\n4) <code>/tt_login</code> → open link → copy <code>code=</code>\n5) <code>/tt_code THE_CODE</code>\n6) <code>/tt_projects</code> → pick list\n7) <code>/tt_push</code> / <code>/tt_pull</code>",
        "tt_setup_ok": "✅ TickTick credentials saved. Now run /tt_login.",
        "tt_setup_usage": "Usage: <code>/tt_setup &lt;client_id&gt; &lt;client_secret&gt;</code>",
        "tt_no_creds": "❌ Run /tt_setup first.",
        "tt_login": "🔗 Open this link, authorize, then copy the <code>code</code> parameter:\n\n{url}\n\nThen send <code>/tt_code YOUR_CODE</code>",
        "tt_code_usage": "Usage: <code>/tt_code &lt;code&gt;</code>",
        "tt_connected": "✅ Connected to TickTick.",
        "tt_fail": "❌ TickTick error: {err}",
        "tt_projects_header": "📚 Choose a target list:",
        "tt_project_set": "✅ Target list set to <b>{name}</b>.",
        "tt_push_done": "✅ Pushed {n} task(s) to TickTick.",
        "tt_pull_done": "✅ Imported {n} task(s) from TickTick.",
        "tt_unlinked": "🔌 TickTick disconnected.",
    },
    "ar": {
        "welcome": "👋 <b>أهلاً بك!</b>\n\nأنا مساعدك الشامل:\n• 📝 قوائم مهام مع تنبيهات مخصّصة\n• 📄 تحويل أي نص إلى ملف txt أو csv\n• 🔄 مزامنة مع TickTick والتطبيقات الأخرى\n• 🌍 العربية والإنجليزية\n\nاكتب /help لعرض كل الأوامر.",
        "help": "<b>الأوامر</b>\n\n/add [النص] – مهمة جديدة\n/list – عرض المهام المتبقية\n/done &lt;الرقم&gt; – إنهاء مهمة\n/del &lt;الرقم&gt; – حذف مهمة\n/remind &lt;الرقم&gt; &lt;الوقت&gt; – ضبط تذكير\n/tofile – تحويل نص إلى ملف\n/export csv|ics|ticktick – تصدير المهام\n/import – استيراد المهام\n\n<b>TickTick</b>\n/tt_setup &lt;client_id&gt; &lt;client_secret&gt;\n/tt_login – رابط التصريح\n/tt_code &lt;code&gt; – إكمال الدخول\n/tt_projects – اختيار القائمة\n/tt_push – إرسال المهام\n/tt_pull – استيراد المهام\n/tt_unlink – قطع الاتصال\n\n<b>الإعدادات</b>\n/lang – تغيير اللغة\n/tz &lt;الفرق&gt; – المنطقة الزمنية\n/cancel – إلغاء",
        "choose_lang": "🌍 اختر لغتك:",
        "lang_set": "✅ تم ضبط اللغة إلى العربية.",
        "tz_usage": "أرسل الفرق عن UTC، مثال <code>/tz +3</code>.",
        "tz_set": "✅ تم ضبط المنطقة الزمنية على UTC{off}. الوقت الحالي: {now}",
        "add_ask_text": "📝 أرسل نص المهمة:",
        "add_ask_time": "⏰ متى أذكّرك؟\n\nأمثلة: <code>30m</code>، <code>2h</code>، <code>14:30</code>\nأو أرسل <code>skip</code>.",
        "time_bad": "❌ لم أفهم الوقت. جرّب <code>30m</code> أو <code>skip</code>.",
        "add_done": "✅ تمت إضافة المهمة #{id}.",
        "add_done_remind": "✅ تمت إضافة المهمة #{id} — سأذكّرك في {when}.",
        "list_empty": "📭 قائمتك فارغة. استخدم /add لإضافة مهمة.",
        "list_header": "📋 <b>مهامك</b> ({n} متبقية):",
        "done_usage": "الاستخدام: <code>/done &lt;الرقم&gt;</code>",
        "done_ok": "✅ تم إنهاء المهمة #{id}.",
        "not_found": "❌ لا توجد مهمة بهذا الرقم.",
        "del_ok": "🗑 تم حذف المهمة #{id}.",
        "remind_usage": "الاستخدام: <code>/remind &lt;الرقم&gt; &lt;الوقت&gt;</code>",
        "remind_set": "⏰ تم ضبط تذكير المهمة #{id} على {when}.",
        "remind_cleared": "🔕 تم إلغاء تذكير المهمة #{id}.",
        "file_ask_text": "📄 أرسل النص الذي تريد تحويله:",
        "file_ask_format": "اختر صيغة الملف:",
        "file_caption": "تفضل ملف {fmt}.",
        "file_empty": "❌ النص فارغ.",
        "export_usage": "الاستخدام: <code>/export csv</code> أو <code>ics</code>",
        "export_empty": "📭 لا توجد مهام للتصدير.",
        "import_usage": "أرسل ملف <b>.csv</b>.",
        "import_done": "✅ تم استيراد {n} مهمة.",
        "import_fail": "❌ تعذّر قراءة ملف CSV.",
        "cancelled": "❎ تم الإلغاء.",
        "unknown": "🤔 لم أفهم ذلك. استخدم /help.",
        "reminder_msg": "🔔 <b>تذكير</b>\n\n{text}",
        "tt_help": "TickTick Setup Steps...",
        "tt_setup_ok": "✅ تم حفظ البيانات. الآن نفّذ /tt_login.",
        "tt_setup_usage": "الاستخدام: <code>/tt_setup &lt;id&gt; &lt;secret&gt;</code>",
        "tt_no_creds": "❌ نفّذ /tt_setup أولاً.",
        "tt_login": "🔗 افتح الرابط: {url} ثم أرسل الكود.",
        "tt_code_usage": "الاستخدام: <code>/tt_code &lt;الكود&gt;</code>",
        "tt_connected": "✅ تم الاتصال.",
        "tt_fail": "❌ خطأ: {err}",
        "tt_projects_header": "📚 اختر القائمة:",
        "tt_project_set": "✅ تم اختيار <b>{name}</b>.",
        "tt_push_done": "✅ تم إرسال {n} مهمة.",
        "tt_pull_done": "✅ تم استيراد {n} مهمة.",
        "tt_unlinked": "🔌 تم قطع الاتصال.",
    },
}

def t(lang: str, key: str, **kw) -> str:
    table = STRINGS.get(lang) or STRINGS["en"]
    s = table.get(key) or STRINGS["en"].get(key, key)
    try:
        return s.format(**kw)
    except Exception:
        return s

def esc(s) -> str:
    return html.escape(str(s))

# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row

def db_init() -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'en', tz INTEGER DEFAULT 0,
            tt_client_id TEXT, tt_client_secret TEXT, tt_redirect TEXT,
            tt_access TEXT, tt_refresh TEXT, tt_expires INTEGER, tt_project TEXT
        );
        CREATE TABLE IF NOT EXISTS todos(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            text TEXT NOT NULL, remind_at INTEGER, reminded INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0, created INTEGER, ext_id TEXT, source TEXT DEFAULT 'local'
        );
        CREATE INDEX IF NOT EXISTS idx_todos_user ON todos(user_id);
    """)
    conn.commit()

USER_COLS = {"lang", "tz", "tt_client_id", "tt_client_secret", "tt_redirect", "tt_access", "tt_refresh", "tt_expires", "tt_project"}

def get_user(uid: int) -> dict:
    cur = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    if row is None:
        conn.execute("INSERT INTO users(user_id) VALUES(?)", (uid,))
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    return dict(row)

def set_user(uid: int, **fields) -> None:
    get_user(uid)
    keys = [k for k in fields if k in USER_COLS]
    if not keys: return
    sql = "UPDATE users SET " + ", ".join(f"{k}=?" for k in keys) + " WHERE user_id=?"
    conn.execute(sql, [fields[k] for k in keys] + [uid])
    conn.commit()

def db_add_todo(uid: int, text: str, remind_at: Optional[int] = None, ext_id: Optional[str] = None, source: str = "local") -> int:
    cur = conn.execute("INSERT INTO todos(user_id, text, remind_at, reminded, done, created, ext_id, source) VALUES(?,?,?,0,0,?,?,?)", (uid, text, remind_at, int(time.time()), ext_id, source))
    conn.commit()
    return int(cur.lastrowid)

def db_get_todo(todo_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
    return dict(row) if row else None

def db_pending(uid: int) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM todos WHERE user_id=? AND done=0 ORDER BY (remind_at IS NULL), remind_at, id", (uid,))]

def db_all_with_reminders() -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM todos WHERE done=0 AND reminded=0 AND remind_at IS NOT NULL")]

def db_mark_done(uid: int, todo_id: int) -> bool:
    cur = conn.execute("UPDATE todos SET done=1, reminded=1 WHERE id=? AND user_id=?", (todo_id, uid))
    conn.commit()
    return cur.rowcount > 0

def db_delete(uid: int, todo_id: int) -> bool:
    cur = conn.execute("DELETE FROM todos WHERE id=? AND user_id=?", (todo_id, uid))
    conn.commit()
    return cur.rowcount > 0

def db_set_reminder(uid: int, todo_id: int, remind_at: Optional[int]) -> bool:
    cur = conn.execute("UPDATE todos SET remind_at=?, reminded=0 WHERE id=? AND user_id=?", (remind_at, todo_id, uid))
    conn.commit()
    return cur.rowcount > 0

def db_mark_reminded(todo_id: int) -> None:
    conn.execute("UPDATE todos SET reminded=1 WHERE id=?", (todo_id,))
    conn.commit()

def db_has_ext(uid: int, ext_id: str) -> bool:
    return conn.execute("SELECT 1 FROM todos WHERE user_id=? AND ext_id=?", (uid, ext_id)).fetchone() is not None

def db_set_ext(todo_id: int, ext_id: str) -> None:
    conn.execute("UPDATE todos SET ext_id=?, source='ticktick' WHERE id=?", (ext_id, todo_id))
    conn.commit()

# ----------------------------------------------------------------------------
# Time Helpers
# ----------------------------------------------------------------------------
class _Skip:
    def __repr__(self): return "SKIP"
SKIP = _Skip()

def parse_relative(s: str) -> Optional[int]:
    s = s.strip().lstrip("+").lower()
    if not re.fullmatch(r"(?:\d+[smhdw])+", s): return None
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    total = 0
    for num, unit in re.findall(r"(\d+)([smhdw])", s):
        total += int(num) * mult[unit]
    return total

def parse_when(raw: str, tz_offset: int):
    raw = (raw or "").strip()
    if raw.lower() in {"skip", "no", "none", "-", "لا", "تخطي", "بدون"}: return SKIP
    rel = parse_relative(raw)
    if rel is not None: return datetime.datetime.now(UTC) + datetime.timedelta(seconds=rel)
    tz = datetime.timezone(datetime.timedelta(minutes=tz_offset))
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M"):
        try: return datetime.datetime.strptime(raw, fmt).replace(tzinfo=tz).astimezone(UTC)
        except ValueError: pass
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            now = datetime.datetime.now(tz)
            dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if dt <= now: dt += datetime.timedelta(days=1)
            return dt.astimezone(UTC)
    return None

def fmt_ts(ts: int, tz_offset: int) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone(datetime.timedelta(minutes=tz_offset))).strftime("%Y-%m-%d %H:%M")

def parse_tz_offset(raw: str) -> Optional[int]:
    raw = raw.strip()
    m = re.fullmatch(r"([+-]?)(\d{1,2})(?::(\d{2}))?", raw)
    if not m:
        try: return int(round(float(raw) * 60))
        except ValueError: return None
    sign = -1 if m.group(1) == "-" else 1
    hours, minutes = int(m.group(2)), int(m.group(3) or 0)
    if hours > 14 or minutes > 59: return None
    return sign * (hours * 60 + minutes)

def tz_label(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"

# ----------------------------------------------------------------------------
# Reminder & Scheduling
# ----------------------------------------------------------------------------
async def reminder_cb(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    todo = db_get_todo(data.get("todo_id")) if data.get("todo_id") else None
    if not todo or todo["done"] or todo["reminded"]: return
    lang = get_user(todo["user_id"])["lang"]
    try:
        await context.bot.send_message(chat_id=data.get("chat_id"), text=t(lang, "reminder_msg", text=esc(todo["text"])), parse_mode=ParseMode.HTML)
    except Exception as exc: log.warning("reminder send failed: %s", exc)
    db_mark_reminded(todo["id"])

def schedule_reminder(job_queue, chat_id: int, todo_id: int, remind_at: int) -> None:
    name = f"todo_{todo_id}"
    for job in job_queue.get_jobs_by_name(name): job.cancel()
    job_queue.run_once(reminder_cb, when=max(0, remind_at - int(time.time())), data={"chat_id": chat_id, "todo_id": todo_id}, name=name)

def cancel_reminder(job_queue, todo_id: int) -> None:
    for job in job_queue.get_jobs_by_name(f"todo_{todo_id}"): job.cancel()

# ----------------------------------------------------------------------------
# Command Handlers
# ----------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    await update.message.reply_text(t(user["lang"], "welcome"), parse_mode=ParseMode.HTML)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    await update.message.reply_text(t(user["lang"], "help"), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    context.user_data.clear()
    await update.message.reply_text(t(user["lang"], "cancelled"))
    return ConversationHandler.END

async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("English 🇬🇧", callback_data="lang:en"), InlineKeyboardButton("العربية 🇸🇦", callback_data="lang:ar")]])
    await update.message.reply_text(t(user["lang"], "choose_lang"), reply_markup=kb)

async def on_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lang = q.data.split(":", 1)[1]
    set_user(q.from_user.id, lang=lang)
    await q.edit_message_text(t(lang, "lang_set"))

async def cmd_tz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    if not context.args:
        await update.message.reply_text(t(user["lang"], "tz_usage"), parse_mode=ParseMode.HTML); return
    off = parse_tz_offset(" ".join(context.args))
    if off is None:
        await update.message.reply_text(t(user["lang"], "tz_usage"), parse_mode=ParseMode.HTML); return
    set_user(user["user_id"], tz=off)
    await update.message.reply_text(t(user["lang"], "tz_set", off=tz_label(off), now=fmt_ts(int(time.time()), off)), parse_mode=ParseMode.HTML)

async def add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    text = " ".join(context.args).strip()
    if text:
        context.user_data["add_text"] = text
        await update.message.reply_text(t(user["lang"], "add_ask_time"), parse_mode=ParseMode.HTML)
        return ADD_TIME
    await update.message.reply_text(t(user["lang"], "add_ask_text"))
    return ADD_TEXT

async def add_got_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    context.user_data["add_text"] = update.message.text.strip()
    await update.message.reply_text(t(user["lang"], "add_ask_time"), parse_mode=ParseMode.HTML)
    return ADD_TIME

async def add_got_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    lang, tz = user["lang"], user["tz"]
    text = context.user_data.get("add_text", "").strip()
    if not text:
        await upda
