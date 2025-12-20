
import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin
import random

# --- KONFIGURASI ---
BASE_URL = "https://kickass-anime.ru/"
OUTPUT_FILE = "anime_hasil_final.json"

# User Agent PC Standar (Penting biar dikira orang beneran)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

async def scrape_kickass_real():
    async with async_playwright() as p:
        # 1. LAUNCH BROWSER DENGAN ARGUMEN "STEALTH"
        # Ini biar browser gak keliatan kayak robot
        browser = await p.chromium.launch(
            headless=True, # Ubah ke False kalau mau lihat browsernya jalan (debugging)
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-position=0,0",
                "--ignore-certifcate-errors",
                "--ignore-certifcate-errors-spki-list",
            ]
        )
        
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
            locale="en-US",
            timezone_id="Asia/Jakarta"
        )
        
        # Buka Homepage
        page = await context.new_page()
        print(f"🚀 Membuka {BASE_URL} ...")
        
        try:
            await page.goto(BASE_URL, timeout=90000, wait_until="domcontentloaded")
            # Tunggu item muncul
            await page.wait_for_selector(".latest-update .show-item", timeout=30000)
        except Exception as e:
            print(f"❌ Gagal akses homepage: {e}")
            await browser.close()
            return

        # Ambil link episode terbaru
        anime_elements = await page.query_selector_all(".latest-update .show-item a.v-card")
        tasks_data = []
        for el in anime_elements:
            href = await el.get_attribute("href")
            if href:
                full_url = urljoin(BASE_URL, href)
                tasks_data.append(full_url)

        print(f"📦 Menemukan {len(tasks_data)} anime. Memproses 10 teratas...\n")
        
        scraped_results = []

        # Loop setiap episode
        for index, ep_url in enumerate(tasks_data[:10]): 
            print(f"🎬 [{index+1}] Sedang membuka: {ep_url}")
            
            ep_page = await context.new_page()
            
            # --- SNIFFER SETUP ---
            m3u8_found = None
            
            async def handle_request(request):
                nonlocal m3u8_found
                url = request.url
                # Ciri link video HLS (bisa dari krussdomi atau server lain)
                if ".m3u8" in url and ("master" in url or "manifest" in url or "playlist" in url):
                    # Filter link iklan sampah
                    if "delivery" not in url and "ad" not in url:
                        print(f"    ⚡ DAPAT LINK: {url}")
                        m3u8_found = url

            ep_page.on("request", handle_request)

            try:
                # Buka Halaman Episode
                await ep_page.goto(ep_url, timeout=60000, wait_until="domcontentloaded")
                
                # --- SCRAPE METADATA (JUDUL) VIA HTML ---
                # Kita pakai CSS Selector dari inspect element lu
                # .v-card__title h1.text-h6
                try:
                    await ep_page.wait_for_selector("h1.text-h6", timeout=15000)
                    
                    judul = await ep_page.inner_text("h1.text-h6")
                    episode = await ep_page.inner_text(".text-overline")
                    poster_div = await ep_page.query_selector(".v-image__image--cover")
                    poster_style = await poster_div.get_attribute("style") if poster_div else ""
                    # Extract url from style string
                    poster = poster_style.split('url("')[1].split('")')[0] if 'url("' in poster_style else ""
                    
                except Exception:
                    # Fallback kalau gagal load
                    print("    ⚠️ Gagal ambil judul (Element belum render), skip metadata...")
                    judul = "Unknown"
                    episode = "Unknown"
                    poster = ""

                # --- CARA PAKSA PLAYER MUNCUL ---
                # 1. Tunggu iframe player
                try:
                    await ep_page.wait_for_selector("iframe.player", timeout=10000)
                except:
                    print("    ⚠️ Iframe player lama muncul, coba scroll...")
                
                # 2. Scroll sedikit biar trigger lazy load
                await ep_page.mouse.wheel(0, 300)
                await ep_page.wait_for_timeout(1000)

                # 3. Tunggu M3U8 Muncul di Network
                for _ in range(15): # Tunggu 7.5 detik max
                    if m3u8_found: break
                    await ep_page.wait_for_timeout(500)
                
                # 4. Kalau belum muncul, KLIK AREA PLAYER
                if not m3u8_found:
                    print("    👆 Link belum keluar, mencoba klik player...")
                    # Klik di tengah-tengah iframe
                    iframe = await ep_page.query_selector("iframe.player")
                    if iframe:
                        box = await iframe.bounding_box()
                        if box:
                            await ep_page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                            await ep_page.wait_for_timeout(3000) # Tunggu loading setelah klik

                # --- SIMPAN HASIL ---
                if m3u8_found:
                    scraped_results.append({
                        "judul": judul,
                        "episode": episode,
                        "url_halaman": ep_url,
                        "url_stream_m3u8": m3u8_found,
                        "poster": poster
                    })
                    print(f"    ✅ SUKSES: {judul} - {episode}")
                else:
                    print("    ❌ GAGAL: Tidak ada stream link yang tertangkap.")

            except Exception as e:
                print(f"    ❌ Error Page: {e}")
            
            finally:
                await ep_page.close()

        await browser.close()

        # Simpan JSON
        if scraped_results:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(scraped_results, f, indent=4, ensure_ascii=False)
            print("\n" + "="*50)
            print(f"✅ BERHASIL! {len(scraped_results)} data tersimpan di {OUTPUT_FILE}")
            print("="*50)
        else:
            print("\n❌ GAGAL TOTAL: Tidak ada data yang berhasil diambil.")

if __name__ == "__main__":
    asyncio.run(scrape_kickass_real())
