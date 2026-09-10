import os
import html
import re
import asyncio
import httpx
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
            for item in data[:8]:
                raw_title = item.get("title", {}).get("rendered", "")
                link = item.get("link", "")
                image = extract_image(item, site["type"])
                if raw_title and link:
                    items.append((clean_title(raw_title), link, image))
        return site["name"], items
    except: return site["name"], []

# --- API جدید استخراج لینک دانلود ---
async def handle_extract(request):
    url = request.query.get("url", "").strip()
    cors_headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET"}
    
    if not url: return web.json_response({"error": "URL missing"}, status=400, headers=cors_headers)
    
    try:
        async with httpx.AsyncClient(verify=False) as client:
            res = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12.0, follow_redirects=True)
            content = res.text
            
            # جستجو برای تگ‌های a که لینک فایل ویدیویی دارند
            a_tags = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', content, re.IGNORECASE | re.DOTALL)
            
            links = []
            seen = set()
            for href, text_html in a_tags:
                href_lower = href.lower()
                if ('.mkv' in href_lower or '.mp4' in href_lower) and href not in seen:
                    clean_text = clean_html_text(text_html)
                    # اگر متنی پیدا نشد، از روی آدرس کیفیت را حدس می‌زنیم
                    if not clean_text or len(clean_text) < 3:
                        if '1080' in href: clean_text = "کیفیت 1080p"
                        elif '720' in href: clean_text = "کیفیت 720p"
                        elif '480' in href: clean_text = "کیفیت 480p"
                        else: clean_text = "لینک دانلود مستقیم"
                    
                    # تمیزکاری بیشتر متن‌ها
                    clean_text = clean_text.replace("دانلود", "").strip()
                    
                    links.append({"title": clean_text[:60], "url": href})
                    seen.add(href)
            
            return web.json_response({"links": links}, headers=cors_headers)
    except Exception as e:
        return web.json_response({"error": str(e), "links": []}, headers=cors_headers)

async def handle_web_search(request):
    query = request.query.get("q", "").strip()
    cors_headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS"}
    if not query: return web.json_response({"results": []}, headers=cors_headers)

    async with httpx.AsyncClient() as client:
        tasks = [fetch_site(client, site, query) for site in SITES]
        responses = await asyncio.gather(*tasks)

    results = []
    for name, items in responses:
        for title, link, image in items:
            results.append({"site": name, "title": title, "link": link, "image": image})
    return web.json_response({"results": results}, headers=cors_headers)

async def handle_options(request):
    return web.Response(status=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type"})
async def handle_ping(request): return web.Response(text="Bot is active!")

async def run_web_server():
    server = web.Application()
    server.router.add_get("/", handle_ping)
    server.router.add_get("/api/search", handle_web_search)
    server.router.add_get("/api/extract", handle_extract) # روت جدید ثبت شد
    server.router.add_route("OPTIONS", "/api/search", handle_options)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# هندلرهای تلگرام
async def start(update, context): await update.message.reply_text("سلام! نام فیلم رو بفرست.")
async def search(update, context): ... # (خلاصه شده برای جلوگیری از شلوغی، تو فایل اصلی خودت هست)

async def main():
    if not TOKEN: raise ValueError("BOT_TOKEN is missing!")
    await run_web_server()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    async with app:
        await app.start()
        await app.updater.start_polling()
        while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
