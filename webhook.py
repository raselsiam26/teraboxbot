import os
import re
import json
import logging
import requests
from urllib.parse import urlparse, quote
from http.server import BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

TERABOX_DOMAINS = [
    "terabox.com", "teraboxapp.com", "1024terabox.com",
    "teraboxlink.com", "terabox.app", "mirrobox.com",
    "nephobox.com", "freeterabox.com", "1024tera.com",
    "4funbox.co", "tibibox.com",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://terabox.com",
    "Referer": "https://terabox.com/",
}


def is_terabox_link(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        return any(host == d.lstrip("www.") for d in TERABOX_DOMAINS)
    except Exception:
        return False


def _is_video_file(name: str) -> bool:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in {"mp4", "mkv", "avi", "mov", "webm", "flv", "m4v", "ts", "3gp"}


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def fetch_terabox_direct(share_url: str) -> dict:
    encoded = quote(share_url, safe="")

    # ── Resolver 1: starlly API (most reliable) ───────────────────────────────
    try:
        api = f"https://starlly.in/terabox.php?url={encoded}"
        r = requests.get(api, headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
        logger.info("Resolver 1 response: %s", data)
        # returns: {status, download_url, title, thumbnail, size}
        if data.get("status") in ("success", "ok", True, "true") or data.get("download_url"):
            direct = data.get("download_url") or data.get("url") or ""
            if direct:
                return {
                    "title":      data.get("title") or data.get("file_name") or "Video",
                    "thumbnail":  data.get("thumbnail") or data.get("thumb"),
                    "direct_url": direct,
                    "size":       str(data.get("size") or "অজানা"),
                    "is_video":   _is_video_file(data.get("title") or ""),
                }
    except Exception as e:
        logger.warning("Resolver 1 failed: %s", e)

    # ── Resolver 2: terabox-dl worker ────────────────────────────────────────
    try:
        api = f"https://teraboxdl.vercel.app/api?url={encoded}"
        r = requests.get(api, headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
        logger.info("Resolver 2 response: %s", data)
        direct = data.get("downloadLink") or data.get("download_url") or data.get("url") or ""
        if direct:
            return {
                "title":      data.get("title") or data.get("filename") or "Video",
                "thumbnail":  data.get("thumbnail") or data.get("thumb"),
                "direct_url": direct,
                "size":       str(data.get("size") or "অজানা"),
                "is_video":   _is_video_file(data.get("title") or ""),
            }
    except Exception as e:
        logger.warning("Resolver 2 failed: %s", e)

    # ── Resolver 3: tb.nadim.workers.dev ─────────────────────────────────────
    try:
        api = f"https://tb.nadim.workers.dev/?url={encoded}"
        r = requests.get(api, headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
        logger.info("Resolver 3 response: %s", data)
        direct = data.get("direct_link") or data.get("download_url") or data.get("url") or ""
        if direct:
            return {
                "title":      data.get("file_name") or data.get("title") or "Video",
                "thumbnail":  data.get("thumbnail"),
                "direct_url": direct,
                "size":       str(data.get("size") or "অজানা"),
                "is_video":   _is_video_file(data.get("file_name") or ""),
            }
    except Exception as e:
        logger.warning("Resolver 3 failed: %s", e)

    # ── Resolver 4: terabox.udayscriptsx ─────────────────────────────────────
    try:
        api = f"https://terabox.udayscriptsx.workers.dev/?url={encoded}"
        r = requests.get(api, headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
        logger.info("Resolver 4 response: %s", data)
        if data.get("status") == "success":
            direct = data.get("direct_url") or data.get("download_url") or ""
            if direct:
                return {
                    "title":      data.get("title") or "Video",
                    "thumbnail":  data.get("thumbnail"),
                    "direct_url": direct,
                    "size":       str(data.get("size") or "অজানা"),
                    "is_video":   _is_video_file(data.get("title") or ""),
                }
    except Exception as e:
        logger.warning("Resolver 4 failed: %s", e)

    raise ValueError(
        "সব resolver fail করেছে।\n"
        "• লিংকটি publicly shared কিনা নিশ্চিত করুন\n"
        "• Terabox-এ লিংকটি এখনও active আছে কিনা দেখুন\n"
        "• কিছুক্ষণ পরে আবার চেষ্টা করুন"
    )


# ── Telegram helpers ──────────────────────────────────────────────────────────

def tg_send(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.error("tg_send error: %s", e)


def tg_send_photo(chat_id, photo, caption, reply_markup=None):
    payload = {"chat_id": chat_id, "photo": photo, "caption": caption, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(f"{TELEGRAM_API}/sendPhoto", json=payload, timeout=10)
        return r.status_code == 200 and r.json().get("ok")
    except Exception:
        return False


def process_message(chat_id, text):
    text = text.strip()

    if text.startswith("/start"):
        tg_send(chat_id,
            "👋 *স্বাগতম Terabox Bot-এ!*\n\n"
            "যেকোনো *Terabox শেয়ার লিংক* পাঠান।\n"
            "সরাসরি টেলিগ্রামে স্ট্রিমিং লিংক পাবেন 🎬\n\n"
            "উদাহরণ:\n`https://terabox.com/s/xxxxxxxx`"
        )
        return

    if text.startswith("/help"):
        tg_send(chat_id,
            "📖 *কিভাবে ব্যবহার করবেন:*\n\n"
            "১. Terabox-এ ভিডিওর শেয়ার লিংক কপি করুন\n"
            "২. এই বটে পাঠান\n"
            "৩. ▶️ Stream বা ⬇️ Download বাটন পাবেন ✅"
        )
        return

    url_match = re.search(r"https?://\S+", text)
    if not url_match:
        tg_send(chat_id, "⚠️ কোনো লিংক পাইনি। একটি Terabox শেয়ার লিংক পাঠান।")
        return

    url = url_match.group(0).rstrip(")")

    if not is_terabox_link(url):
        tg_send(chat_id, "❌ এটি Terabox লিংক মনে হচ্ছে না।")
        return

    tg_send(chat_id, "⏳ লিংক প্রসেস হচ্ছে...")

    try:
        info = fetch_terabox_direct(url)
    except ValueError as exc:
        tg_send(chat_id, f"❌ *সমস্যা হয়েছে:*\n{exc}")
        return
    except Exception as e:
        logger.exception("Unexpected error")
        tg_send(chat_id, "❌ অপ্রত্যাশিত সমস্যা। পরে আবার চেষ্টা করুন।")
        return

    direct = info["direct_url"]
    title  = info["title"]
    size   = info["size"]
    emoji  = "🎬" if info["is_video"] else "📁"
    thumb  = info.get("thumbnail")

    caption = (
        f"{emoji} *{title}*\n"
        f"📦 সাইজ: `{size}`\n\n"
        "নিচের বাটনে ক্লিক করুন:"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "▶️ Stream / Watch", "url": direct},
            {"text": "⬇️ Download", "url": direct},
        ]]
    }

    if thumb:
        ok = tg_send_photo(chat_id, thumb, caption, keyboard)
        if ok:
            return

    tg_send(chat_id, caption, keyboard)


# ── Vercel handler ────────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            update = json.loads(body)

            msg = update.get("message") or update.get("edited_message")
            if msg:
                chat_id = msg["chat"]["id"]
                text    = msg.get("text", "")
                if text:
                    process_message(chat_id, text)
        except Exception as e:
            logger.exception("Webhook error: %s", e)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Terabox Bot is alive!")

    def log_message(self, *args):
        pass
