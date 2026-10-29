#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
All-in-one Telegram assistant bot.

Features
--------
1) To-do list with custom one-shot reminders (relative or absolute times).
2) Convert any text into a .txt or .csv file.
3) Sync with TickTick (Open API) + generic CSV / ICS import-export.
4) Full Arabic / English support (per-user language + timezone).

Requirements:
    pip install "python-telegram-bot[job-queue]" httpx

Run:
    export BOT_TOKEN="123456:ABC..."
    python bot.py

Env vars (optional):
    BOT_DB       sqlite file path (default: bot.db)
"""

import os
import io
import re
import csv
import time
import html
import logging
import sqlite3
import datetime
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
# i18n
# ----------------------------------------------------------------------------
STRINGS = {
    "en": {
        "welcome": (
            "👋 <b>Welcome!</b>\n\n"
            "I'm your all-in-one assistant:\n"
            "• 📝 To-do lists with custom reminders\n"
            "• 📄 Turn any text into .txt / .csv files\n"
            "• 🔄 Sync with TickTick and other apps\n"
            "• 🌍 Arabic & English\n\n"
            "Use /help to see every command."
        ),
        "help": (
            "<b>Commands</b>\n\n"
            "/add [text] – new task (then send the reminder time)\n"
            "/list – show your pending tasks\n"
            "/done &lt;id&gt; – mark a task as done\n"
            "/del &lt;id&gt; – delete a task\n"
            "/remind &lt;id&gt; &lt;time&gt; – set/change a reminder\n"
            "/tofile – convert text into a .txt or .csv file\n"
            "/export csv|ics|ticktick – export your tasks\n"
            "/import – send me a CSV file to import tasks\n\n"
            "<b>TickTick</b>\n"
            "/tt_setup &lt;client_id&gt; &lt;client_secret&gt; [redirect_uri]\n"
            "/tt_login – get the authorization link\n"
            "/tt_code &lt;code&gt; – finish login\n"
            "/tt_projects – choose the target list\n"
            "/tt_push – send local tasks to TickTick\n"
            "/tt_pull – import tasks from TickTick\n"
            "/tt_unlink – disconnect\n\n"
            "<b>Settings</b>\n"
            "/lang – change language\n"
            "/tz &lt;offset&gt; – timezone, e.g. /tz +3 or /tz -5.5 or /tz +05:30\n"
            "/cancel – abort the current step\n\n"
            "<b>Time formats</b>\n"
            "<code>30m</code> · <code>2h30m</code> · <code>1d</code> (relative)\n"
            "<code>2025-01-30 14:30</code> (absolute)\n"
            "<code>14:30</code> (today, or tomorrow if already past)\n"
            "Send <code>skip</code> to save a task without a reminder."
        ),
        "choose_lang": "🌍 Choose your language:",
        "lang_set": "✅ Language set to English.",
        "tz_usage": "Send the offset from UTC, e.g. <code>/tz +3</code>, <code>/tz -5.5</code> or <code>/tz +05:30</code>.",
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
        "tt_help": (
            "<b>TickTick</b>\n\n"
            "1) Create an app at <a href=\"https://developer.ticktick.com/manage\">developer.ticktick.com</a>\n"
            "2) Set the redirect URI to <code>http://localhost:8080/callback</code>\n"
            "3) <code>/tt_setup CLIENT_ID CLIENT_SECRET</code>\n"
            "4) <code>/tt_login</code> → open the link → copy the <code>code=</code> value\n"
            "5) <code>/tt_code THE_CODE</code>\n"
            "6) <code>/tt_projects</code> → pick a list\n"
            "7) <code>/tt_push</code> / <code>/tt_pull</code>"
        ),
        "tt_setup_ok": "✅ TickTick credentials saved. Now run /tt_login.",
        "tt_setup_usage": "Usage: <code>/tt_setup &lt;client_id&gt; &lt;client_secret&gt; [redirect_uri]</code>",
        "tt_no_creds": "❌ Run /tt_setup first.",
        "tt_login": "🔗 Open this link, authorize, then copy the <code>code</code> parameter from the URL you land on:\n\n{url}\n\nThen send <code>/tt_code YOUR_CODE</code>",
        "tt_code_usage": "Usage: <code>/tt_code &lt;authorization_code&gt;</code>",
        "tt_connected": "✅ Connected to TickTick.",
        "tt_fail": "❌ TickTick error: {err}",
        "tt_projects_header": "📚 Choose a target list:",
        "tt_project_set": "✅ Target list set to <b>{name}</b>.",
        "tt_push_done": "✅ Pushed {n} task(s) to TickTick.",
        "tt_pull_done": "✅ Imported {n} task(s) from TickTick.",
        "tt_unlinked": "🔌 TickTick disconnected.",
    },
    "ar": {
        "welcome": (
            "👋 <b>أهلاً بك!</b>\n\n"
            "أنا مساعدك الشامل:\n"
            "• 📝 قوائم مهام مع تنبيهات مخصّصة\n"
            "• 📄 تحويل أي نص إلى ملف txt أو csv\n"
            "• 🔄 مزامنة مع TickTick والتطبيقات الأخرى\n"
            "• 🌍 العربية والإنجليزية\n\n"
            "اكتب /help لعرض كل الأوامر."
        ),
        "help": (
            "<b>الأوامر</b>\n\n"
            "/add [النص] – مهمة جديدة (ثم أرسل وقت التذكير)\n"
            "/list – عرض المهام المتبقية\n"
            "/done &lt;الرقم&gt; – إنهاء مهمة\n"
            "/del &lt;الرقم&gt; – حذف مهمة\n"
            "/remind &lt;الرقم&gt; &lt;الوقت&gt; – ضبط أو تغيير التذكير\n"
            "/tofile – تحويل نص إلى ملف txt أو csv\n"
            "/export csv|ics|ticktick – تصدير المهام\n"
            "/import – أرسل ملف CSV لاستيراد المهام\n\n"
            "<b>TickTick</b>\n"
            "/tt_setup &lt;client_id&gt; &lt;client_secret&gt; [redirect_uri]\n"
            "/tt_login – رابط التصريح\n"
            "/tt_code &lt;code&gt; – إكمال تسجيل الدخول\n"
            "/tt_projects – اختيار القائمة\n"
            "/tt_push – إرسال المهام إلى TickTick\n"
            "/tt_pull – استيراد المهام من TickTick\n"
            "/tt_unlink – قطع الاتصال\n\n"
            "<b>الإعدادات</b>\n"
            "/lang – تغيير اللغة\n"
            "/tz &lt;الفرق&gt; – المنطقة الزمنية، مثال /tz +3 أو /tz -5.5 أو /tz +05:30\n"
            "/cancel – إلغاء الخطوة الحالية\n\n"
            "<b>صيغ الوقت</b>\n"
            "<code>30m</code> · <code>2h30m</code> · <code>1d</code> (نسبي)\n"
            "<code>2025-01-30 14:30</code> (مطلق)\n"
            "<code>14:30</code> (اليوم أو غداً إن مضى)\n"
            "أرسل <code>skip</code> لحفظ المهمة بدون تذكير."
        ),
        "choose_lang": "🌍 اختر لغتك:",
        "lang_set": "✅ تم ضبط اللغة إلى العربية.",
        "tz_usage": "أرسل الفرق عن UTC، مثال <code>/tz +3</code> أو <code>/tz -5.5</code> أو <code>/tz +05:30</code>.",
        "tz_set": "✅ تم ضبط المنطقة الزمنية على UTC{off}. الوقت الحالي: {now}",
        "add_ask_text": "📝 أرسل نص المهمة:",
        "add_ask_time": "⏰ متى أذكّرك؟\n\nأمثلة: <code>30m</code>، <code>2h</code>، <code>2025-01-30 14:30</code>، <code>14:30</code>\nأو أرسل <code>skip</code>.",
        "time_bad": "❌ لم أفهم الوقت. جرّب <code>30m</code> أو <code>2h30m</code> أو <code>2025-01-30 14:30</code> أو <code>skip</code>.",
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
        "file_ask_text": "📄 أرسل النص الذي تريد تحويله إلى ملف:",
        "file_ask_format": "اختر صيغة الملف:",
        "file_caption": "تفضل ملف {fmt}.",
        "file_empty": "❌ النص فارغ.",
        "export_usage": "الاستخدام: <code>/export csv</code> أو <code>/export ics</code> أو <code>/export ticktick</code>",
        "export_empty": "📭 لا توجد مهام للتصدير.",
        "import_usage": "أرسل ملف <b>.csv</b> (كل سطر مهمة، العمود الأول هو النص).",
        "import_done": "✅ تم استيراد {n} مهمة.",
        "import_fail": "❌ تعذّر قراءة ملف CSV.",
        "cancelled": "❎ تم الإلغاء.",
        "unknown": "🤔 لم أفهم ذلك. استخدم /help لعرض الإمكانيات.",
        "reminder_msg": "🔔 <b>تذكير</b>\n\n{text}",
        "tt_help": (
            "<b>TickTick</b>\n\n"
            "1) أنشئ تطبيقاً على <a href=\"https://developer.ticktick.com/manage\">developer.ticktick.com</a>\n"
            "2) ضع رابط الإعادة <code>http://localhost:8080/callback</code>\n"
            "3) <code>/tt_setup CLIENT_ID CLIENT_SECRET</code>\n"
            "4) <code>/tt_login</code> ← افتح الرابط وانسخ قيمة <code>code=</code>\n"
            "5) <code>/tt_code THE_CODE</code>\n"
            "6) <code>/tt_projects</code> ← اختر قائمة\n"
            "7) <code>/tt_push</code> / <code>/tt_pull</code>"
        ),
        "tt_setup_ok": "✅ تم حفظ بيانات TickTick. الآن نفّذ /tt_login.",
        "tt_setup_usage": "الاستخدام: <code>/tt_setup &lt;client_id&gt; &lt;client_secret&gt; [redirect_uri]</code>",
        "tt_no_creds": "❌ نفّذ /tt_setup أولاً.",
        "tt_login": "🔗 افتح الرابط واسمح بالوصول، ثم انسخ قيمة <code>code</code> من الرابط:\n\n{url}\n\nثم أرسل <code>/tt_code الكود</code>",
        "tt_code_usage": "الاستخدام: <code>/tt_code &lt;الكود&gt;</code>",
        "tt_connected": "✅ تم الاتصال بـ TickTick.",
        "tt_fail": "❌ خطأ من TickTick: {err}",
        "tt_projects_header": "📚 اختر القائمة الهدف:",
        "tt_project_set": "✅ تم اختيار القائمة <b>{name}</b>.",
        "tt_push_done": "✅ تم إرسال {n} مهمة إلى TickTick.",
        "tt_pull_done": "✅ تم استيراد {n} مهمة من TickTick.",
        "tt_unlinked": "🔌 تم قطع الاتصال بـ TickTick.",
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
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            user_id     INTEGER PRIMARY KEY,
            lang        TEXT DEFAULT 'en',
            tz          INTEGER DEFAULT 0,
            tt_client_id     TEXT,
            tt_client_secret TEXT,
            tt_redirect      TEXT,
            tt_access        TEXT,
            tt_refresh       TEXT,
            tt_expires       INTEGER,
            tt_project       TEXT
        );
        CREATE TABLE IF NOT EXISTS todos(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            text        TEXT NOT NULL,
            remind_at   INTEGER,
            reminded    INTEGER DEFAULT 0,
            done        INTEGER DEFAULT 0,
            created     INTEGER,
            ext_id      TEXT,
            source      TEXT DEFAULT 'local'
        );
        CREATE INDEX IF NOT EXISTS idx_todos_user ON todos(user_id);
        """
    )
    conn.commit()


USER_COLS = {
    "lang", "tz",
    "tt_client_id", "tt_client_secret", "tt_redirect",
    "tt_access", "tt_refresh", "tt_expires", "tt_project",
}


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
    if not keys:
        return
    sql = "UPDATE users SET " + ", ".join(f"{k}=?" for k in keys) + " WHERE user_id=?"
    conn.execute(sql, [fields[k] for k in keys] + [uid])
    conn.commit()


def db_add_todo(uid: int, text: str, remind_at: Optional[int] = None,
                ext_id: Optional[str] = None, source: str = "local") -> int:
    cur = conn.execute(
        "INSERT INTO todos(user_id, text, remind_at, reminded, done, created, ext_id, source) "
        "VALUES(?,?,?,0,0,?,?,?)",
        (uid, text, remind_at, int(time.time()), ext_id, source),
    )
    conn.commit()
    return int(cur.lastrowid)


def db_get_todo(todo_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
    return dict(row) if row else None


def db_pending(uid: int) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM todos WHERE user_id=? AND done=0 ORDER BY "
        "(remind_at IS NULL), remind_at, id", (uid,))]


def db_all_with_reminders() -> list:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM todos WHERE done=0 AND reminded=0 AND remind_at IS NOT NULL")]


def db_mark_done(uid: int, todo_id: int) -> bool:
    cur = conn.execute("UPDATE todos SET done=1, reminded=1 WHERE id=? AND user_id=?",
                       (todo_id, uid))
    conn.commit()
    return cur.rowcount > 0


def db_delete(uid: int, todo_id: int) -> bool:
    cur = conn.execute("DELETE FROM todos WHERE id=? AND user_id=?", (todo_id, uid))
    conn.commit()
    return cur.rowcount > 0


def db_set_reminder(uid: int, todo_id: int, remind_at: Optional[int]) -> bool:
    cur = conn.execute(
        "UPDATE todos SET remind_at=?, reminded=0 WHERE id=? AND user_id=?",
        (remind_at, todo_id, uid))
    conn.commit()
    return cur.rowcount > 0


def db_mark_reminded(todo_id: int) -> None:
    conn.execute("UPDATE todos SET reminded=1 WHERE id=?", (todo_id,))
    conn.commit()


def db_has_ext(uid: int, ext_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM todos WHERE user_id=? AND ext_id=?",
                       (uid, ext_id)).fetchone()
    return row is not None


def db_set_ext(todo_id: int, ext_id: str) -> None:
    conn.execute("UPDATE todos SET ext_id=?, source='ticktick' WHERE id=?",
                 (ext_id, todo_id))
    conn.commit()


# ----------------------------------------------------------------------------
# Time helpers
# ----------------------------------------------------------------------------
class _Skip:
    def __repr__(self):
        return "SKIP"


SKIP = _Skip()


def parse_relative(s: str) -> Optional[int]:
    s = s.strip().lstrip("+").lower()
    if not re.fullmatch(r"(?:\d+[smhdw])+", s):
        return None
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    total = 0
    for num, unit in re.findall(r"(\d+)([smhdw])", s):
        total += int(num) * mult[unit]
    return total


def parse_when(raw: str, tz_offset: int):
    """Return aware UTC datetime, SKIP, or None if unparseable."""
    raw = (raw or "").strip()
    low = raw.lower()
    if low in {"skip", "no", "none", "-", "لا", "تخطي", "بدون"}:
        return SKIP

    rel = parse_relative(raw)
    if rel is not None:
        return datetime.datetime.now(UTC) + datetime.timedelta(seconds=rel)

    tz = datetime.timezone(datetime.timedelta(minutes=tz_offset))
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.datetime.strptime(raw, fmt).replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            pass

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            now = datetime.datetime.now(tz)
            dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if dt <= now:
                dt += datetime.timedelta(days=1)
            return dt.astimezone(UTC)
    return None


def fmt_ts(ts: int, tz_offset: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts, datetime.timezone(
        datetime.timedelta(minutes=tz_offset)))
    return dt.strftime("%Y-%m-%d %H:%M")


def parse_tz_offset(raw: str) -> Optional[int]:
    """'+3' -> 180, '-5.5' -> -330, '+05:30' -> 330"""
    raw = raw.strip()
    m = re.fullmatch(r"([+-]?)(\d{1,2})(?::(\d{2}))?", raw)
    if not m:
        try:
            hours = float(raw)
            return int(round(hours * 60))
        except ValueError:
            return None
    sign = -1 if m.group(1) == "-" else 1
    hours = int(m.group(2))
    minutes = int(m.group(3) or 0)
    if hours > 14 or minutes > 59:
        return None
    return sign * (hours * 60 + minutes)


def tz_label(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


# ----------------------------------------------------------------------------
# Reminder scheduling
# ----------------------------------------------------------------------------
async def reminder_cb(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    todo_id = data.get("todo_id")
    chat_id = data.get("chat_id")
    todo = db_get_todo(todo_id)
