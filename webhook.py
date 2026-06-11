import os
import re
import json
import logging
import requests
from urllib.parse import urlparse, parse_qs
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
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.terabox.com/",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    # Resolver 1
    try:
        proxy = f"https://terabox.udayscriptsx.workers.dev/?url={share_url}"
        resp = requests.get(proxy, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            direct_url = data.get("direct_url") or data.get("download_url") or ""
            if direct_url:
                return {
                    "title":      data.get("title") or "Video",
                    "thumbnail":  data.get("thumbnail"),
                    "direct_url": direct_url,
                    "size":       data.get("size") or "অজানা",
                    "is_video":   _is_video_file(data.get("title") or ""),
                }
    except Exception as e:
        logger.warning("Resolver 1 failed: %s", e)

    # Resolver 2
    try:
        api_url = f"https://teraboxapp.com/api/shorturlinfo?shorturl={share_url}"
        resp = requests.get(api_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        file_list = data.get("list", [])
        if file_list:
            item      = file_list[0]
            title     = item.get("server_filename") or "Video"
            thumbs    = item.get("thumbs") or {}
            thumbnail = thumbs.get("url3") or thumbs.get("url1")
            direct    = item.get("dlink") or item.get("download_link") or ""
            size_b    = int(item.get("size", 0))
            if direct:
                return {
                    "title":      title,
                    "thumbnail":  thumbnail,
                    "direct_url": direct,
                    "size":       _human_size(size_b),
                    "is_video":   _is_video_file(title),
                }
    except Exception as e:
        logger.warning("Resolver 2 failed: %s", e)

    raise ValueError(
        "লিংকটি resolve করা যায়নি।\n"
        "• লিংকটি সঠিক কিনা চেক করুন\n"
        "• publicly shared কিনা নিশ্চিত করুন\n"
        "• কিছুক্ষণ পরে আবার চেষ্টা করুন"
    )


# ── Telegram API calls ────────────────────────────────────────────────────────

def tg_send(chat_id: int, text: str, reply_markup=None, parse_mode="Markdown"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)


def tg_send_photo(chat_id: int, photo: str, caption: str, reply_markup=None):
    payload = {"chat_id": chat_id, "photo": photo, "caption": caption, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(f"{TELEGRAM_API}/sendPhoto", json=payload, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def process_message(chat_id: int, text: str):
    text = text.strip()

    # Commands
    if text in ("/start", "/start@" + get_bot_username()):
        tg_send(chat_id,
            "👋 *স্বাগতম Terabox Bot-এ!*\n\n"
            "যেকোনো *Terabox শেয়ার লিংক* পাঠান।\n"
            "সরাসরি টেলিগ্রামে স্ট্রিমিং লিংক পাবেন 🎬\n\n"
            "উদাহরণ:\n`https://terabox.com/s/xxxxxxxx`"
        )
        return

    if text in ("/help", "/help@" + get_bot_username()):
        tg_send(chat_id,
            "📖 *কিভাবে ব্যবহার করবেন:*\n\n"
            "১. Terabox-এ ভিডিওর শেয়ার লিংক কপি করুন\n"
            "২. এই বটে পাঠান\n"
            "৩. ▶️ Stream বা ⬇️ Download বাটন পাবেন ✅"
        )
        return

    # Extract URL
    url_match = re.search(r"https?://\S+", text)
    if not url_match:
        tg_send(chat_id, "⚠️ কোনো লিংক পাইনি। একটি Terabox শেয়ার লিংক পাঠান।")
        return

    url = url_match.group(0).rstrip(")")

    if not is_terabox_link(url):
        tg_send(chat_id, "❌ এটি Terabox লিংক মনে হচ্ছে না।\nসঠিক Terabox শেয়ার লিংক পাঠান।")
        return

    # Processing notice
    tg_send(chat_id, "⏳ লিংক প্রসেস হচ্ছে...")

    try:
        info = fetch_terabox_direct(url)
    except ValueError as exc:
        tg_send(chat_id, f"❌ *সমস্যা হয়েছে:*\n{exc}")
        return
    except Exception:
        tg_send(chat_id, "❌ অপ্রত্যাশিত সমস্যা। পরে আবার চেষ্টা করুন।")
        return

    direct = info["direct_url"]
    title  = info["title"]
    size   = info["size"]
    is_vid = info["is_video"]
    thumb  = info.get("thumbnail")
    emoji  = "🎬" if is_vid else "📁"

    caption = (
        f"{emoji} *{title}*\n"
        f"📦 সাইজ: `{size}`\n\n"
        "▶️ Stream বাটনে ক্লিক করলে সরাসরি চলবে।\n"
        "⬇️ Download বাটন দিয়ে সেভ করুন।"
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


_bot_username = None
def get_bot_username():
    global _bot_username
    if not _bot_username:
        try:
            r = requests.get(f"{TELEGRAM_API}/getMe", timeout=5)
            _bot_username = r.json().get("result", {}).get("username", "")
        except Exception:
            _bot_username = ""
    return _bot_username


# ── Vercel serverless handler ─────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            update = json.loads(body)

            message = update.get("message") or update.get("edited_message")
            if message:
                chat_id = message["chat"]["id"]
                text    = message.get("text", "")
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
        self.wfile.write(b"Terabox Bot is running!")

    def log_message(self, *args):
        pass  # suppress default access logs
