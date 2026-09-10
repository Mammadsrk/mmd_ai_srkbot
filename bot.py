import os
import html
import re
import time
import random
import string
import asyncio
import httpx
from urllib.parse import urljoin
from aiohttp import web
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

TOKEN = os.environ.get("BOT_TOKEN")

SITES = [
    {"name": "دوستی‌ها", "api": "https://www.doostihaa.com/wp-json/wp/v2/posts?search=", "type": "wp"},
    {"name": "زردفیلم", "api": "https://zardfilm.in/wp-json/wp/v2/posts?search=", "type": "wp"},
    {"name": "هکس‌دانلود", "api": "https://hexdownload.co/wp-json/wp/v2/posts?search=", "type": "wp"},
    {"name": "فیلم‌تو‌مووی", "api": "https://www.myf2m.net/wp-json/wp/v2/posts?search=", "type": "wp"},
    {"name": "زرین‌پخش", "api": "https://zarinpakhsh.ir/wp-json/wp/v2/posts?search=", "type": "wp"},
    {"name": "فیلمچی", "api": "https://filmchi.net/wp-json/wp/v2/posts?search=", "type": "wp"}
]

def clean_title(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"^(دانلود|فیلم|سریال|انیمیشن|سینمایی)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(با\s+دوبله\s+فارسی|زیرنویس\s+چسبیده|دوبله\s+فارسی|فارسی).*$", "", text, flags=re.IGNORECASE)
    return text.strip() or "مشاهده لینک"

def clean_html_text(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def extract_image(item, site_type):
    if site_type == "nxm":
        return item.get("thumb") or item.get("poster") or item.get("pic") or ""
    elif site_type == "wp":
        if item.get("jetpack_featured_media_url"): return item.get("jetpack_featured_media_url")
        yoast = item.get("yoast_head_json", {})
        if isinstance(yoast, dict):
            og_images = yoast.get("og_image", [])
            if isinstance(og_images, list) and len(og_images) > 0:
                return og_images[0].get("url", "")
        content = item.get("content", {}).get("rendered", "")
        if content:
            match = re.search(r'(?:src|data-src|data-lazy-src)\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
            if match: return match.group(1)
            match = re.search(r'https?://[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)', content, re.IGNORECASE)
            if match: return match.group(0)
    return ""

async def fetch_site(client: httpx.AsyncClient, site: dict, query: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"{site['api']}{query}"
        res = await client.get(url, headers=headers, timeout=8.0, follow_redirects=True)
        if res.status_code != 200: return site["name"], []
        
        data = res.json()
        items = []
        if isinstance(data, list):
            for item in data[:6]:
                raw_title = item.get("title", {}).get("rendered", "")
                link = item.get("link", "")
                image = extract_image(item, site["type"])
                post_id = item.get("id", "")
                if raw_title and link:
                    items.append((clean_title(raw_title), link, image, post_id))
        return site["name"], items
    except Exception:
        return site["name"], []

# موتور استخراج لینک‌های دانلود فایل
async def extract_download_links(url: str) -> list:
    try:
        async with httpx.AsyncClient(verify=False) as client:
            req_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "X-Forwarded-For": "5.200.14.15",
                "X-Real-IP": "5.200.14.15"
            }
            res = await client.get(url, headers=req_headers, timeout=12.0, follow_redirects=True)
            content = res.text
            
            a_tags = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', content, re.IGNORECASE | re.DOTALL)
            links = []
            seen = set()
            video_exts = ['.mkv', '.mp4', '.avi', '.m4v', '.mov', '.ts', '.m3u8']
            
            for href, text_html in a_tags:
                href = urljoin(url, href)
                if not href.startswith('http'): continue
                href_lower = href.lower()
                clean_text = clean_html_text(text_html)
                
                has_video_ext = any(ext in href_lower for ext in video_exts) or 'upera.tv' in href_lower or 'hub.hxdl.ir' in href_lower
                is_junk = any(x in href_lower for x in ['t.me', 'telegram', 'instagram', '/tag/', '/category/'])
                
                if has_video_ext and not is_junk and href not in seen:
                    href = href.replace('http://', 'https://')
                    if len(clean_text) < 3:
                        clean_text = "لینک دانلود"
                    links.append({"title": clean_text[:40], "url": href})
                    seen.add(href)
            return links
    except Exception:
        return []

# =====================================================================
# هندلرهای تلگرام (کامل و اصلاح شده)
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 سلام! نام فیلم یا سریال مورد نظرت رو برام بفرست تا بگردم.")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        return

    wait_msg = await update.message.reply_text("🔍 در حال جستجو در تمامی سایت‌ها...")
    
    async with httpx.AsyncClient() as client:
        tasks = [fetch_site(client, site, query) for site in SITES]
        responses = await asyncio.gather(*tasks)

    output = []
    found_any = False

    for name, items in responses:
        if items:
            found_any = True
            output.append(f"<b>🌐 {name}:</b>")
            # رفع باگ Unpack با استفاده از 4 متغیر:
            for title, link, _, _ in items:
                output.append(f"  ▫️ <a href=\"{link}\">{html.escape(title)}</a>")
            output.append("")

    if not found_any:
        await wait_msg.edit_text("❌ متأسفانه فیلم یا سریالی با این عنوان یافت نشد.")
        return

    text = "\n".join(output)
    if len(text) > 4000:
        text = text[:4000] + "..."

    await wait_msg.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# =====================================================================
# وب سرور و APIها
# =====================================================================
async def handle_ping(request): 
    return web.Response(text="Bot is active!")

async def handle_web_search(request):
    query = request.query.get("q", "").strip()
    cors_headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS"}
    if not query: return web.json_response({"results": []}, headers=cors_headers)

    async with httpx.AsyncClient() as client:
        tasks = [fetch_site(client, site, query) for site in SITES]
        responses = await asyncio.gather(*tasks)

    results = []
    for name, items in responses:
        for title, link, image, _ in items:
            results.append({"site": name, "title": title, "link": link, "image": image})
    return web.json_response({"results": results}, headers=cors_headers)

async def handle_extract(request):
    url = request.query.get("url", "").strip()
    cors_headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET"}
    if not url: return web.json_response({"error": "URL missing"}, status=400, headers=cors_headers)
    
    links = await extract_download_links(url)
    return web.json_response({"links": links}, headers=cors_headers)

async def handle_options(request):
    return web.Response(status=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type"})

async def run_web_server():
    server = web.Application()
    server.router.add_get("/", handle_ping)
    server.router.add_get("/api/search", handle_web_search)
    server.router.add_get("/api/extract", handle_extract)
    server.router.add_route("OPTIONS", "/api/search", handle_options)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    if not TOKEN: 
        raise ValueError("BOT_TOKEN is missing!")
    await run_web_server()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))
    async with app:
        await app.start()
        await app.updater.start_polling()
        while True: 
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
