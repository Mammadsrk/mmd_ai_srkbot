import os
import re
import html
import asyncio
import httpx
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "1d5c680c4118cd9d172f1e762db4c69e")

SITES = [
    {"id": "doostihaa", "name": "Doostihaa", "nameFa": "دوستی‌ها", "domain": "doostihaa.com", "api": "https://www.doostihaa.com/wp-json/wp/v2/posts?search="},
    {"id": "zardfilm", "name": "Zardfilm", "nameFa": "زردفیلم", "domain": "zardfilm.in", "api": "https://zardfilm.in/wp-json/wp/v2/posts?search="},
    {"id": "film2movie", "name": "Film2Movie", "nameFa": "فیلم‌تومووی", "domain": "myf2m.net", "api": "https://www.myf2m.net/wp-json/wp/v2/posts?search="},
    {"id": "hexdownload", "name": "HexDownload", "nameFa": "هکس‌دانلود", "domain": "hexdownload.co", "api": "https://hexdownload.co/wp-json/wp/v2/posts?search="},
    {"id": "zarinpakhsh", "name": "ZarinPakhsh", "nameFa": "زرین‌پخش", "domain": "zarinpakhsh.ir", "api": "https://zarinpakhsh.ir/wp-json/wp/v2/posts?search="},
    {"id": "filmchi", "name": "Filmchi", "nameFa": "فیلمچی", "domain": "filmchi.net", "api": "https://filmchi.net/wp-json/wp/v2/posts?search="}
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

async def check_single_site(client: httpx.AsyncClient, site: dict, query: str):
    try:
        url = f"{site['api']}{query}&per_page=1"
        res = await client.get(url, headers=IRAN_HEADERS, timeout=3.0, follow_redirects=True)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                return {"site": site["name"], "nameFa": site["nameFa"], "available": True, "link": data[0].get("link", "")}
    except Exception:
        pass
    return {"site": site["name"], "nameFa": site["nameFa"], "available": False, "link": f"https://{site['domain']}/?s={query}"}

# ==================== استخراج آپارات و نماشا با تفکیک دوبله و زیرنویس ====================
async def search_movie_variants(title_fa: str, title_en: str):
    clean_fa = re.sub(r'[0-9]{4}', '', title_fa).strip()
    result = {"dubbed": None, "subbed": None}

    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(headers=headers, timeout=4.5) as client:
        # ۱. سرچ نسخه دوبله
        try:
            res_dub = await client.get(f"https://www.aparat.com/api/fa/v1/video/video/search/text/{clean_fa} دوبله فارسی")
            if res_dub.status_code == 200:
                for v in res_dub.json().get("included", []):
                    attr = v.get("attributes", {})
                    dur = int(attr.get("duration", 0) or 0)
                    if dur >= 1800 and attr.get("uid"):
                        det = await client.get(f"https://www.aparat.com/api/fa/v1/video/video/show/videohash/{attr['uid']}")
                        if det.status_code == 200:
                            d_attr = det.json().get("data", {}).get("attributes", {})
                            file_links = d_attr.get("file_link_all", [])
                            quals = [{"text": f.get("text") or f"کیفیت {f.get('profile', 'HD')}", "url": f["urls"][0]} for f in file_links if f.get("urls")]
                            quals.reverse()
                            result["dubbed"] = {
                                "title": d_attr.get("title") or attr.get("title"),
                                "duration": f"{round(dur/60)} دقیقه",
                                "streamUrl": quals[0]["url"] if quals else d_attr.get("file_link", ""),
                                "qualities": quals
                            }
                            break
        except Exception:
            pass

        # ۲. سرچ نسخه زیرنویس
        try:
            res_sub = await client.get(f"https://www.aparat.com/api/fa/v1/video/video/search/text/{clean_fa} زیرنویس فارسی")
            if res_sub.status_code == 200:
                for v in res_sub.json().get("included", []):
                    attr = v.get("attributes", {})
                    dur = int(attr.get("duration", 0) or 0)
                    if dur >= 1800 and attr.get("uid"):
                        det = await client.get(f"https://www.aparat.com/api/fa/v1/video/video/show/videohash/{attr['uid']}")
                        if det.status_code == 200:
                            d_attr = det.json().get("data", {}).get("attributes", {})
                            file_links = d_attr.get("file_link_all", [])
                            quals = [{"text": f.get("text") or f"کیفیت {f.get('profile', 'HD')}", "url": f["urls"][0]} for f in file_links if f.get("urls")]
                            quals.reverse()
                            result["subbed"] = {
                                "title": d_attr.get("title") or attr.get("title"),
                                "duration": f"{round(dur/60)} دقیقه",
                                "streamUrl": quals[0]["url"] if quals else d_attr.get("file_link", ""),
                                "qualities": quals
                            }
                            break
        except Exception:
            pass

    return result

# ==================== اندپوینت دریافت مشخصات جامع TMDB ====================
async def handle_movie_details(request):
    title = request.query.get("title", "").strip()
    title_fa = request.query.get("titleFa", title).strip()
    media_type = request.query.get("type", "movie").strip()
    tmdb_id = request.query.get("tmdbId", "").strip()

    clean_en = re.sub(r'[0-9]{4}', '', title).strip()
    clean_fa = re.sub(r'[0-9]{4}', '', title_fa).strip()

    detail_data = {
        "title": clean_en,
        "titleFa": clean_fa,
        "type": media_type,
        "overviewFa": "خلاصه داستانی برای این اثر ثبت نشده است.",
        "rating": 7.5,
        "releaseYear": "2024",
        "runtime": "120 دقیقه" if media_type == "movie" else "مجموعه تلویزیونی",
        "director": "سینمای بین‌الملل",
        "cast": ["ستارگان مطرح سینما"],
        "posterUrl": "",
        "backdropUrl": "",
        "genres": ["سینمایی", "اکشن"],
        "trailers": [],
        "sources": [],
        "movieFiles": None
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        # دریافت جزئیات، پوسترها، تریلر و بازیگران از TMDB
        if tmdb_id and TMDB_API_KEY:
            try:
                tmdb_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}&append_to_response=videos,credits&language=fa-IR"
                res = await client.get(tmdb_url)
                if res.status_code == 200:
                    d = res.json()
                    detail_data["overviewFa"] = d.get("overview") or detail_data["overviewFa"]
                    detail_data["titleFa"] = d.get("title") or d.get("name") or detail_data["titleFa"]
                    detail_data["rating"] = round(d.get("vote_average", 7.5), 1)
                    detail_data["backdropUrl"] = f"https://image.tmdb.org/t/p/original{d.get('backdrop_path')}" if d.get("backdrop_path") else ""
                    detail_data["posterUrl"] = f"https://image.tmdb.org/t/p/w500{d.get('poster_path')}" if d.get("poster_path") else ""
                    if d.get("runtime"): detail_data["runtime"] = f"{d['runtime']} دقیقه"
                    if d.get("genres"): detail_data["genres"] = [g["name"] for g in d["genres"]]
                    
                    # بازیگران و کارگردان
                    if d.get("credits", {}).get("cast"):
                        detail_data["cast"] = [c["name"] for c in d["credits"]["cast"][:6]]
                    if d.get("credits", {}).get("crew"):
                        dir_item = next((c["name"] for c in d["credits"]["crew"] if c.get("job") == "Director"), None)
                        if dir_item: detail_data["director"] = dir_item

                    # تریلر یوتیوب
                    for v in d.get("videos", {}).get("results", []):
                        if v.get("site") == "YouTube" and v.get("key"):
                            detail_data["trailers"].append({
                                "name": "سرور جهانی (یوتیوب)",
                                "url": f"https://www.youtube-nocookie.com/embed/{v['key']}?autoplay=1",
                                "site": "YouTube"
                            })
                            break
            except Exception:
                pass

        # تریلر آپارات (مخصوص ایران بدون فیلترشکن)
        try:
            ap_res = await client.get(f"https://www.aparat.com/api/fa/v1/video/video/search/text/{clean_fa} تریلر")
            if ap_res.status_code == 200:
                vids = ap_res.json().get("included", [])
                if vids:
                    frame = vids[0].get("attributes", {}).get("frame")
                    if frame:
                        detail_data["trailers"].insert(0, {
                            "name": "سرور داخلی (آپارات - بدون فیلترشکن)",
                            "url": frame,
                            "site": "Aparat"
                        })
        except Exception:
            pass

        # مراجع ۶ سایت ایرانی
        for s in SITES:
            detail_data["sources"].append({
                "nameFa": s["nameFa"],
                "domain": s["domain"],
                "url": f"https://{s['domain']}/?s={clean_fa}"
            })

    # اگر فیلم سینمایی بود، نسخه‌های دوبله و زیرنویس آپارات را استخراج کن
    if media_type == "movie":
        detail_data["movieFiles"] = await search_movie_variants(clean_fa, clean_en)

    return web.json_response({"success": True, "data": detail_data}, headers=CORS_HEADERS)

# ==================== سایر Routeها ====================
async def handle_check_sources(request):
    query = request.query.get("query", "").strip()
    if not query: return web.json_response({"sources": []}, headers=CORS_HEADERS)
    clean_q = re.sub(r'[0-9]{4}', '', query).strip()
    async with httpx.AsyncClient() as client:
        tasks = [check_single_site(client, site, clean_q) for site in SITES]
        results = await asyncio.gather(*tasks)
    return web.json_response({"sources": results}, headers=CORS_HEADERS)

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
                        "tmdbId": m.get("id"),
                        "type": media_type,
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
    server.router.add_get("/", lambda r: web.Response(text="MMD Engine Active"))
    server.router.add_get("/api/check-sources", handle_check_sources)
    server.router.add_get("/api/movie-details", handle_movie_details)
    server.router.add_get("/api/tmdb/{type}", handle_tmdb_trending)
    server.router.add_route("OPTIONS", "/{tail:.*}", handle_options)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    if not TOKEN: raise ValueError("BOT_TOKEN is missing!")
    await run_web_server()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("MMD FILM Online!")))
    async with app:
        await app.start()
        await app.updater.start_polling()
        while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
