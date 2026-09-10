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
        "name": "نکست‌مووی",
        "api": "https://w.mihan-cdn.com/api/v3/search",
        "type": "nxm"
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
        "Referer": "https://nxmweb.com/",
        "Origin": "https://nxmweb.com",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        if site["type"] == "nxm":
            res = await client.post(
                site["api"],
                data={"q": query, "page": "1"},
                params={"q": query, "page": 1},
                headers=headers,
                timeout=8.0
            )
            if res.status_code != 200:
                res = await client.get(
                    f"{site['api']}?q={query}&page=1",
                    headers=headers,
                    timeout=8.0
                )
        else:
            res = await client.get(
                f"{site['api']}{query}",
                headers=headers,
                timeout=8.0,
                follow_redirects=True
            )

        if res.status_code != 200:
            return site["name"], []
        
        data = res.json()
        items = []

        if site["type"] == "nxm":
            results = data if isinstance(data, list) else data.get("data", [])
            for item in results[:5]:
                title = clean_title(item.get("title_fa") or item.get("title_en") or item.get("title") or "")
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
    await update.message.reply_text("سلام! نام اثر مورد نظرت رو بفرست تا در سایت‌ها برات جستجو کنم.")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    wait_msg = await update.message.reply_text("در حال جستجو...")

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
