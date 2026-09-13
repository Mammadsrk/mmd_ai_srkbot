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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Forwarded-For": "5.200.14.15",
    "X-Real-IP": "5.200.14.15"
}

def clean_title(raw: str) -> str:
    t = re.sub(r"<[^>]+>", "", raw)
    t = html.unescape(t)
    t = re.sub(r"^(دانلود|فیلم|سریال|انیمیشن|سینمایی)\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+(با\s+دوبله\s+فارسی|زیرنویس\s+چسبیده|دوبله\s+فارسی|فارسی).*$", "", t, flags=re.IGNORECASE)
    return t.strip() or "مشاهده فیلم"

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

async def search_aparat_full_movie(query: str):
    clean_fa = re.sub(r'[0-9]{4}', '', query).strip()
    search_queries = [f"{clean_fa} فیلم کامل", f"{clean_fa} دوبله فارسی", clean_fa]

    async with httpx.AsyncClient(headers=IRAN_HEADERS, timeout=5.0) as client:
        # ۱. سرچ آپارات
        for q_text in search_queries:
            try:
                search_url = f"https://www.aparat.com/api/fa/v1/video/video/search/text/{q_text}"
                res = await client.get(search_url)
                if res.status_code == 200:
                    data = res.json()
                    videos = [it for it in data.get("included", []) if it.get("type") == "Video"]
                    for v in videos[:10]:
                        attr = v.get("attributes", {})
                        dur = int(attr.get("duration", 0) or 0)
                        uid = attr.get("uid")
                        if dur >= 1800 and uid: # فیلم کامل بالای ۳۰ دقیقه
                            detail_res = await client.get(f"https://www.aparat.com/api/fa/v1/video/video/show/videohash/{uid}")
                            if detail_res.status_code == 200:
                                d_data = detail_res.json()
                                d_attr = d_data.get("data", {}).get("attributes", {})
                                file_links = d_attr.get("file_link_all", [])
                                qualities = []
                                for f in file_links:
                                    if f.get("urls") and len(f["urls"]) > 0:
                                        qualities.append({
                                            "text": f.get("text") or f"کیفیت {f.get('profile', 'استاندارد')}",
                                            "url": f["urls"][0]
                                        })
                                qualities.reverse()
                                stream_url = qualities[0]["url"] if qualities else d_attr.get("file_link", "")
                                return {
                                    "available": True,
                                    "provider": "Aparat",
                                    "title": d_attr.get("title") or attr.get("title"),
                                    "durationFormatted": f"{round(dur/60)} دقیقه",
                                    "embedUrl": f"https://www.aparat.com/video/video/embed/videohash/{uid}/vt/frame",
                                    "qualities": qualities,
                                    "streamUrl": stream_url or d_attr.get("hls_link", ""),
                                    "vlcUrl": f"vlc://{stream_url}" if stream_url else ""
                                }
            except Exception:
                continue

        # ۲. سرچ نماشا (Fallback)
        try:
            namasha_url = f"https://www.namasha.com/search?q={clean_fa} کامل"
            res = await client.get(namasha_url)
            if res.status_code == 200:
                matches = re.findall(r'<a href="(https://www.namasha.com/v/([a-zA-Z0-9]+))"', res.text)
                if matches:
                    page_url, uid = matches[0]
                    v_res = await client.get(page_url)
                    if v_res.status_code == 200:
                        src_matches = re.findall(r"'file':\s*'([^']+\.mp4)',\s*'label':\s*'([^']+)'", v_res.text)
                        if src_matches:
                            qualities = [{"text": f"کیفیت {m[1]}", "url": m[0]} for m in src_matches]
                            stream_url = qualities[0]["url"]
                            return {
                                "available": True,
                                "provider": "Namasha",
                                "title": f"پخش آنلاین {clean_fa}",
                                "durationFormatted": "فیلم کامل",
                                "embedUrl": f"https://www.namasha.com/embed/{uid}",
                                "qualities": qualities,
                                "streamUrl": stream_url,
                                "vlcUrl": f"vlc://{stream_url}"
                            }
        except Exception:
            pass

    return {"available": False}

# ==================== API Endpoints ====================
async def handle_ping(request):
    return web.Response(text="MMD FILM Online")

async def handle_check_sources(request):
    query = request.query.get("query", "").strip()
    if not query: return web.json_response({"sources": []}, headers=CORS_HEADERS)
    clean_q = re.sub(r'[0-9]{4}', '', query).strip()
    async with httpx.AsyncClient() as client:
        tasks = [check_single_site(client, site, clean_q) for site in SITES]
        results = await asyncio.gather(*tasks)
    return web.json_response({"sources": results}, headers=CORS_HEADERS)

async def handle_aparat(request):
    q = request.query.get("q", "").strip()
    data = await search_aparat_full_movie(q)
    return web.json_response({"success": True, "data": data}, headers=CORS_HEADERS)

async def handle_tmdb(request):
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
    server.router.add_get("/api/aparat/full-movie", handle_aparat)
    server.router.add_get("/api/tmdb/{type}", handle_tmdb)
    server.router.add_route("OPTIONS", "/{tail:.*}", handle_options)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 سرور و بات آماده به کار است.")

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
