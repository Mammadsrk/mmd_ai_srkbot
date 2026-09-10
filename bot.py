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
        "name": "نکست‌مووی",
        "api": "https://w.mihan-cdn.com/api/v3/search?page=1&q=",
        "type": "nxm"
    },
    {
        "name": "زردفیلم",
        "api": "https://zardfilm.in/wp-json/wp/v2/posts?search=",
        "type": "wp"
    },
    {
        "name": "دوستی‌ها",
        "api": "https://www.doostihaa.com/wp-json/wp/v2/posts?search=",
        "type": "wp"
    },
    {
        "name": "مووی‌شو",
        "api": "https://www.moviesho.com/wp-json/wp/v2/posts?search=",
        "type": "wp"
    }
]

def clean_title(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"(دانلود|فیلم|سریال|انیمیشن|سینمایی|فصل\s+\d+|قسمت\s+\d+).*", "", text, flags=re.IGNORECASE)
    return text.strip() or "عنوان نامشخص"

async def fetch_site(client: httpx.AsyncClient, site: dict, query: str):
    url = f"{site['api']}{query}"
    try:
        res = await client.get(url, timeout=5.0)
        if res.status_code != 200:
            return site["name"], []
        
        data = res.json()
        items = []

        if site["type"] == "nxm":
            results = data if isinstance(data, list) else data.get("data", [])
            for item in results[:5]:
                title = clean_title(item.get("title_fa") or item.get("title") or "")
                movie_id = item.get("id") or item.get("movie_id")
                if movie_id:
                    items.append((title, f"https://nxmweb.com/details/{movie_id}"))

        elif site["type"] == "wp":
            results = data if isinstance(data, list) else []
            for item in results[:5]:
                raw_title = item.get("title", {}).get("rendered", "")
                link = item.get("link", "")
                if raw_title and link:
                    items.append((clean_title(raw_title), link))

        return site["name"], items
    except Exception:
        return site["name"], []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! نام فیلم یا سریال مورد نظرت رو بفرست تا در سایت‌ها جستجو کنم.")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    wait_msg = await update.message.reply_text("در حال جستجو...")

    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        responses = [await fetch_site(client, site, query) for site in SITES]

    output = []
    for name, items in responses:
        if items:
            output.append(f"▫️ <b>{name}</b>:")
            for title, link in items:
                safe_title = html.escape(title)
                output.append(f"  • <a href=\"{link}\">{safe_title}</a>")
        else:
            output.append(f"▫️ <b>{name}</b>: نتیجه‌ای یافت نشد.")

    text = "\n".join(output)
    await wait_msg.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# سرور ساختگی برای راضی نگه داشتن رندر
async def handle_ping(request):
    return web.Response(text="Bot is active and running!")

async def run_web_server():
    server = web.Application()
    server.router.add_get("/", handle_ping)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is not set in environment variables!")
    
    # اجرای وب‌سرور در پس‌زمینه
    await run_web_server()

    # اجرای بات تلگرام
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))

    async with app:
        await app.start()
        await app.updater.start_polling()
        # فعال نگه داشتن لوپ
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
