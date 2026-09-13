import os
import re
import html
import asyncio
import httpx
from aiohttp import web
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

TOKEN = os.environ.get("BOT_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "1d5c680c4118cd9d172f1e762db4c69e")

SITES = [
    {"id": "doostihaa", "name": "Doostihaa", "nameFa": "دوستی‌ها", "api": "https://www.doostihaa.com/wp-json/wp/v2/posts?search="},
    {"id": "zardfilm", "name": "Zardfilm", "nameFa": "زردفیلم", "api": "https://zardfilm.in/wp-json/wp/v2/posts?search="},
    {"id": "film2movie", "name": "Film2Movie", "nameFa": "فیلم‌تومووی", "api": "https://www.myf2m.net/wp-json/wp/v2/posts?search="},
    {"id": "hexdownload", "name": "HexDownload", "nameFa": "هکس‌دانلود", "api": "https://hexdownload.co/wp-json/wp/v2/posts?search="},
    {"id": "zarinpakhsh", "name": "ZarinPakhsh", "nameFa": "زرین‌پخش", "api": "https://zarinpakhsh.ir/wp-json/wp/v2/posts?search="},
    {"id": "filmchi", "name": "Filmchi", "nameFa": "فیلمچی", "api": "https://filmchi.net/wp-json/wp/v2/posts?search="}
]

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
}

IRAN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "X-Forwarded-For": "5.200.14.15",
    "X-Real-IP": "5.200.14.15"
}

def clean_title(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"^(دانلود|فیلم|سریال|انیمیشن|سینمایی)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(با\s+دوبله\s+فارسی|زیرنویس\s+چسبیده|دوبله\s+فارسی|فارسی).*$", "", text, flags=re.IGNORECASE)
    return text.strip() or "مشاهده لینک"

async def check_single_site(client: httpx.AsyncClient, site: dict, query: str):
    try:
        url = f"{site['api']}{query}&per_page=1"
        res = await client.get(url, headers=IRAN_HEADERS, timeout=3.5, follow_redirects=True)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                return {"site": site["name"], "nameFa": site["nameFa"], "available": True, "link": data[0].get("link", "")}
    except Exception:
        pass
    return {"site": site["name"], "nameFa": site["nameFa"], "available": False, "link": ""}

# =====================================================================
# موتور جستجو و استخراج فیلم کامل از آپارات و نماشا (منطق استودیو)
# =====================================================================
async def search_aparat_full_movie(query: str):
    clean_q = re.sub(r'[0-9]{4}', '', query).strip()
    search_url = f"https://www.aparat.com/api/fa/v1/video/video/search/text/{clean_q} فیلم کامل"
    
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(search_url, timeout=4.5)
            if res.status_code == 200:
                data = res.json()
                videos = [it for it in data.get("included", []) if it.get("type") == "Video"]
                
                for v in videos[:8]:
                    attr = v.get("attributes", {})
                    dur = int(attr.get("duration", 0) or 0)
                    uid = attr.get("uid")
                    # فیلم سینمایی کامل (بالای ۳۵ دقیقه = ۲۱۰۰ ثانیه)
                    if dur >= 2100 and uid:
                        detail_res = await client.get(f"https://www.aparat.com/api/fa/v1/video/video/show/videohash/{uid}", timeout=4.0)
                        if detail_res.status_code == 200:
                            d_data = detail_res.json()
                            d_attr = d_data.get("data", {}).get("attributes", {})
                            file_links = d_attr.get("file_link_all", [])
                            
                            qualities = []
                            for f in file_links:
                                if f.get("urls") and len(f["urls"]) > 0:
                                    qualities.append({
                                        "text": f.get("text") or f"کیفیت {f.get('profile', 'استاندارد')}",
                                        "profile": f.get("profile", "720p"),
                                        "url": f["urls"][0]
                                    })
                            qualities.reverse() # بالاترین کیفیت اول
                            
                            stream_url = qualities[0]["url"] if qualities else d_attr.get("file_link", "")
                            hls_url = d_attr.get("hls_link", "")
                            
                            return {
                                "available": True,
                                "provider": "Aparat",
                                "providerNameFa": "آپارات",
                                "title": d_attr.get("title") or attr.get("title"),
                                "durationFormatted": f"{round(dur/60)} دقیقه",
                                "embedUrl": f"https://www.aparat.com/video/video/embed/videohash/{uid}/vt/frame",
                                "pageUrl": f"https://www.aparat.com/v/{uid}",
                                "qualities": qualities,
                                "streamUrl": stream_url or hls_url,
                                "vlcUrl": f"vlc://{stream_url}" if stream_url else ""
                            }
    except Exception:
        pass
    return {"available": False}

# =====================================================================
# API Endpoints
# =====================================================================
async def handle_ping(request):
    return web.Response(text="MMD FILM Engine Active!")

async def handle_check_sources(request):
    query = request.query.get("query", "").strip()
    if not query:
        return web.json_response({"sources": []}, headers=CORS_HEADERS)
    
    clean_q = re.sub(r'[0-9]{4}', '', query).strip()
    async with httpx.AsyncClient() as client:
        tasks = [check_single_site(client, site, clean_q) for site in SITES]
        results = await asyncio.gather(*tasks)
        
    return web.json_response({"query": query, "sources": results}, headers=CORS_HEADERS)

async def handle_aparat_movie(request):
    q = request.query.get("q", "").strip()
    if not q:
        return web.json_response({"available": False}, headers=CORS_HEADERS)
    data = await search_aparat_full_movie(q)
    return web.json_response({"success": True, "data": data}, headers=CORS_HEADERS)

async def handle_tmdb_trending(request):
    media_type = request.match_info.get("type", "movie")
    url = f"https://api.themoviedb.org/3/trending/{media_type}/week?api_key={TMDB_API_KEY}&language=fa-IR"
    
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                results = []
                for m in data.get("results", [])[:14]:
                    results.append({
                        "id": str(m.get("id")),
                        "title": m.get("original_title") or m.get("original_name") or m.get("title") or m.get("name"),
                        "titleFa": m.get("title") or m.get("name"),
                        "posterUrl": f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}" if m.get("poster_path") else "",
                        "rating": round(m.get("vote_average", 7.5), 1),
                        "releaseYear": (m.get("release_date") or m.get("first_air_date") or "2024").split("-")[0]
                    })
                return web.json_response({"results": results}, headers=CORS_HEADERS)
    except Exception:
        pass
    return web.json_response({"results": []}, headers=CORS_HEADERS)

async def handle_options(request):
    return web.Response(status=204, headers=CORS_HEADERS)

async def run_web_server():
    server = web.Application()
    server.router.add_get("/", handle_ping)
    server.router.add_get("/api/check-sources", handle_check_sources)
    server.router.add_get("/api/aparat/full-movie", handle_aparat_movie)
    server.router.add_get("/api/tmdb/{type}", handle_tmdb_trending)
    server.router.add_route("OPTIONS", "/{tail:.*}", handle_options)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 MMD FILM آماده است!")

async def main():
    if not TOKEN: raise ValueError("BOT_TOKEN is missing!")
    await run_web_server()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    async with app:
        await app.start()
        await app.updater.start_polling()
        while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
