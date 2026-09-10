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
    {
        "name": "دوستی‌ها",
        "api": "https://www.doostihaa.com/wp-json/wp/v2/posts?search=",
        "type": "wp"
    },
    {
        "name": "زردفیلم",
        "api": "https://zardfilm.in/wp-json/wp/v2/posts?search=",
        "type": "wp"
    },
    {
        "name": "هکس‌دانلود",
        "api": "https://hexdownload.co/wp-json/wp/v2/posts?search=",
        "type": "wp"
    },
    {
        "name": "فیلم‌تو‌مووی",
        "api": "https://www.myf2m.net/wp-json/wp/v2/posts?search=",
        "type": "wp"
    },
    {
        "name": "زرین‌پخش",
        "api": "https://zarinpakhsh.ir/wp-json/wp/v2/posts?search=",
        "type": "wp"
    },
    {
        "name": "فیلمچی",
        "api": "https://filmchi.net/wp-json/wp/v2/posts?search=",
        "type": "wp"
    }
]

def clean_title(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"^(دانلود|فیلم|سریال|انیمیشن|سینمایی)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(با\s+دوبله\s+فارسی|زیرنویس\s+چسبیده|دوبله\s+فارسی|فارسی).*$", "", text, flags=re.IGNORECASE)
    return text.strip() or "مشاهده لینک"

async def fetch_site(client: httpx.AsyncClient, site: dict, query: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        url = f"{site['api']}{query}"
        res = await client.get(url, headers=headers, timeout=8.0, follow_redirects=True)

        if res.status_code != 200:
            return site["name"], []
        
        data = res.json()
        items = []

        if isinstance(data, list):
            for item in data[:4]:
                raw_title = item.get("title", {}).get("rendered", "")
                link = item.get("link", "")
                if raw_title and link:
                    items.append((clean_title(raw_title), link))

        return site["name"], items
    except Exception:
        return site["name"], []

# هندلرهای تلگرام
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! نام فیلم یا سریال مورد نظرت رو بفرست تا بین ۶ سایت معتبر و رایگان جستجو کنم.")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    wait_msg = await update.message.reply_text("در حال جستجو در سایت‌ها...")

    async with httpx.AsyncClient() as client:
        tasks = [fetch_site(client, site, query) for site in SITES]
        responses = await asyncio.gather(*tasks)

    output = []
    for name, items in responses:
        if items:
            output.append(f"▫️ <b>{name}</b>:")
            for title, link in items:
                output.append(f"  • <a href=\"{link}\">{html.escape(title)}</a>")
        else:
            output.append(f"▫️ <b>{name}</b>: نتیجه‌ای یافت نشد.")

    text = "\n".join(output)
    await wait_msg.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# هندلرهای وب‌سرور برای سایت و آپتایم‌ربات
async def handle_ping(request):
    return web.Response(text="Backend is active and running!")

async def handle_web_search(request):
    query = request.query.get("q", "").strip()
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }

    if not query:
        return web.json_response({"results": []}, headers=cors_headers)

    async with httpx.AsyncClient() as client:
        tasks = [fetch_site(client, site, query) for site in SITES]
        responses = await asyncio.gather(*tasks)

    results = []
    for name, items in responses:
        for title, link in items:
            results.append({
                "site": name,
                "title": title,
                "link": link
            })

    return web.json_response({"results": results}, headers=cors_headers)

async def handle_options(request):
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }
    return web.Response(status=204, headers=cors_headers)

async def run_web_server():
    server = web.Application()
    server.router.add_get("/", handle_ping)
    server.router.add_get("/api/search", handle_web_search)
    server.router.add_route("OPTIONS", "/api/search", handle_options)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is not set in environment variables!")
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
