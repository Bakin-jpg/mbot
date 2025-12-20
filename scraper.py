import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin
import os

# --- KONFIGURASI ---
BASE_URL = "https://kickass-anime.ru/"
OUTPUT_FILE = "anime_data_complete.json"

async def main():
    async with async_playwright() as p:
        # Browser Setup
        browser = await p.chromium.launch(
            headless=True, 
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        # Context dengan Referer diset ke Base URL biar server video gak nolak akses
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            extra_http_headers={"Referer": BASE_URL}
        )
        
        page = await context.new_page()

        # 1. BUKA HOMEPAGE & AMBIL LIST
        print(f"🔥 Membuka Homepage: {BASE_URL}")
        try:
            await page.goto(BASE_URL, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_selector(".latest-update .show-item", timeout=30000)
        except Exception as e:
            print(f"❌ Gagal load home: {e}")
            await browser.close()
            return

        # Scrape List Anime dari Homepage
        # Kita ambil elemen container-nya dulu biar gampang ambil poster & link
        items = await page.query_selector_all(".latest-update .show-item")
        print(f"📦 Ditemukan {len(items)} anime terbaru. Memulai eksekusi...")

        anime_list = []
        for item in items:
            try:
                # Ambil Link
                link_el = await item.query_selector("a.v-card")
                href = await link_el.get_attribute("href")
                full_link = urljoin(BASE_URL, href)
                
                # Ambil Poster (Dari style background-image)
                img_el = await item.query_selector(".v-image__image--cover")
                style = await img_el.get_attribute("style")
                poster = style.split('url("')[1].split('")')[0] if 'url("' in style else ""
                if poster and not poster.startswith("http"): poster = urljoin(BASE_URL, poster)

                anime_list.append({
                    "link": full_link,
                    "poster": poster
                })
            except: continue

        results = []

        # 2. LOOPING MASUK KE SETIAP EPISODE
        for i, anime in enumerate(anime_list):
            print(f"\n🎬 [{i+1}/{len(anime_list)}] Proses: {anime['link']}")
            
            page_ep = await context.new_page()
            
            try:
                await page_ep.goto(anime['link'], timeout=60000, wait_until="domcontentloaded")
                
                # --- A. AMBIL METADATA (JUDUL & EPISODE) ---
                try:
                    await page_ep.wait_for_selector("h1.text-h6", timeout=10000)
                    judul = await page_ep.inner_text("h1.text-h6")
                    episode = await page_ep.inner_text(".text-overline")
                except:
                    judul = "Unknown Title"
                    episode = "Unknown Ep"

                # --- B. AMBIL URL IFRAME ---
                iframe_src = None
                try:
                    # Tunggu iframe player muncul
                    iframe_el = await page_ep.wait_for_selector("iframe.player", timeout=15000)
                    iframe_src = await iframe_el.get_attribute("src")
                    # Fix URL kalau relative
                    if iframe_src.startswith("//"): iframe_src = "https:" + iframe_src
                except:
                    print("    ⚠️ Iframe tidak ditemukan di page ini.")

                # Tutup page episode, kita udah dapet iframe-nya
                await page_ep.close()

                # --- C. KONVERSI IFRAME -> M3U8 (SNIFFING) ---
                final_m3u8 = None
                if iframe_src:
                    print(f"    🔗 Iframe dapat: {iframe_src}")
                    print("    🕵️‍♂️ Melakukan sniffing M3U8...")
                    
                    page_sniff = await context.new_page()
                    
                    # Listener
                    async def sniff(request):
                        nonlocal final_m3u8
                        # Filter ketat: harus .m3u8 dan tipe master/playlist
                        if ".m3u8" in request.url and ("master" in request.url or "manifest" in request.url):
                            final_m3u8 = request.url

                    page_sniff.on("request", sniff)

                    try:
                        # Buka Iframe langsung
                        await page_sniff.goto(iframe_src, timeout=30000, wait_until="domcontentloaded")
                        
                        # Tunggu traffic lewat
                        for _ in range(10): # 5 detik
                            if final_m3u8: break
                            await page_sniff.wait_for_timeout(500)
                            
                    except: pass
                    await page_sniff.close()

                # --- SIMPAN DATA ---
                if final_m3u8:
                    print(f"    ✅ SUKSES M3U8: {final_m3u8}")
                    results.append({
                        "judul": judul,
                        "episode": episode,
                        "poster": anime['poster'],
                        "url_page": anime['link'],
                        "url_iframe": iframe_src,
                        "url_hls": final_m3u8 # <--- INI YG PENTING
                    })
                else:
                    print("    ❌ GAGAL convert ke M3U8.")

            except Exception as e:
                print(f"    ❌ Error process: {e}")
                if not page_ep.is_closed(): await page_ep.close()

        await browser.close()

        # Output JSON
        with open(OUTPUT_FILE, "w", encoding='utf-8') as f:
            json.dump(results, f, indent=4, ensure_ascii=False)
        print(f"\n✅ SELESAI BOS. Cek file: {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
