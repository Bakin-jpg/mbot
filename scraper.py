import asyncio
from playwright.async_api import async_playwright
import json
import random
from urllib.parse import urljoin

# --- KONFIGURASI ---
BASE_URL = "https://kickass-anime.ru/"
OUTPUT_FILE = "anime_hasil_sukses.json"

async def scrape_kaa_visible():
    print("🔥 MEMULAI SCRAPER MODE VISUAL (ANTI-BLOKIR) 🔥")
    print("Jendela Browser akan terbuka, JANGAN DITUTUP!")
    
    async with async_playwright() as p:
        # 1. GUNAKAN BROWSER VISUAL (HEADLESS=FALSE)
        # Ini kuncinya biar server kasih data
        browser = await p.chromium.launch(
            headless=False, # <--- PENTING: Harus False biar gak diblokir
            channel="chrome", # Pakai Chrome asli di PC lu (kalau ada), lebih kebal detect
            args=[
                "--disable-blink-features=AutomationControlled", # Sembunyikan identitas bot
                "--start-maximized", # Buka layar penuh
                "--no-sandbox"
            ]
        )
        
        # Setup context biar cookies kesimpen (kayak orang browsing biasa)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US"
        )
        
        # Tambahkan script stealth tambahan ke browser
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page = await context.new_page()
        
        # 2. BUKA HOMEPAGE & CARI LIST ANIME
        print(f"\n🚀 Membuka {BASE_URL} ...")
        try:
            await page.goto(BASE_URL, timeout=60000)
            # Tunggu loading agak lamaan biar Cloudflare lewat
            await page.wait_for_timeout(5000) 
            
            # Cari elemen anime (sesuai inspect element lu)
            # Kita cari class "show-item"
            await page.wait_for_selector(".show-item", state="visible", timeout=30000)
            
        except Exception as e:
            print(f"❌ Gagal loading Homepage: {e}")
            print("Mungkin perlu solve CAPTCHA manual? (Script akan tunggu 15 detik)")
            await page.wait_for_timeout(15000) # Kasih waktu user solve captcha kalau muncul
            
        # Ambil semua link dari homepage
        all_links = await page.query_selector_all(".show-item a.v-card")
        tasks_data = []
        for link in all_links:
            href = await link.get_attribute("href")
            if href:
                tasks_data.append(urljoin(BASE_URL, href))
        
        # Hapus duplikat
        tasks_data = list(set(tasks_data))
        print(f"📦 Menemukan {len(tasks_data)} link anime.")
        
        scraped_results = []
        
        # 3. LOOPING BUKA TAB BARU UNTUK SETIAP EPISODE
        # Batasi 5 dulu buat testing
        for i, url in enumerate(tasks_data[:5]):
            print(f"\n🎬 [{i+1}] Memproses: {url}")
            
            new_page = await context.new_page()
            
            # Variabel buat nangkep link m3u8
            m3u8_url = None
            
            # Setup Sniffer
            async def handle_request(request):
                nonlocal m3u8_url
                req_url = request.url
                # Filter ketat link m3u8
                if ".m3u8" in req_url and "master" in req_url:
                    print(f"    ⚡ NETWORK DETECTED: {req_url}")
                    m3u8_url = req_url
            
            new_page.on("request", handle_request)
            
            try:
                await new_page.goto(url, timeout=60000)
                
                # Trik Psikologis Browser: Tunggu render & gerakan mouse dikit
                await new_page.wait_for_timeout(3000)
                await new_page.mouse.move(100, 100)
                await new_page.mouse.move(500, 500)
                
                # Tunggu metadata muncul (Judul Anime)
                try:
                    title_el = await new_page.wait_for_selector("h1.text-h6", timeout=10000)
                    judul = await title_el.inner_text()
                    
                    ep_el = await new_page.query_selector(".text-overline")
                    episode = await ep_el.inner_text() if ep_el else "Ep ?"
                except:
                    print("    ⚠️ Metadata belum render, mencoba scroll...")
                    judul = "Unknown Title"
                    episode = "Unknown Ep"
                    # Scroll ke bawah untuk memicu lazy load
                    await new_page.mouse.wheel(0, 500)
                
                # --- LOGIKA PLAYER ---
                # Tunggu iframe player muncul
                try:
                    # Cari iframe yang src-nya mengandung player/krussdomi
                    iframe_el = await new_page.wait_for_selector("iframe[src*='player']", timeout=15000)
                    if iframe_el:
                        # Scroll ke iframe biar ke-load
                        await iframe_el.scroll_into_view_if_needed()
                        
                        # Tunggu m3u8 muncul di network
                        print("    ⏳ Menunggu player loading...")
                        for _ in range(10): # Tunggu 10 detik max
                            if m3u8_url: break
                            await new_page.wait_for_timeout(1000)
                            
                        # Kalau masih gak muncul, coba KLIK iframenya
                        if not m3u8_url:
                            print("    👆 Mengklik player secara paksa...")
                            # Klik koordinat tengah iframe
                            box = await iframe_el.bounding_box()
                            if box:
                                await new_page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                                await new_page.wait_for_timeout(3000)

                except Exception as e:
                    print(f"    ⚠️ Player tidak ditemukan: {e}")

                # Hasil Akhir Episode Ini
                if m3u8_url:
                    scraped_results.append({
                        "judul": judul,
                        "episode": episode,
                        "url_halaman": url,
                        "stream_url": m3u8_url
                    })
                    print(f"    ✅ SUKSES DAPAT: {m3u8_url}")
                else:
                    print("    ❌ GAGAL: M3U8 tidak muncul di network traffic.")

            except Exception as e:
                print(f"    ❌ Error membuka page: {e}")
            
            finally:
                await new_page.close()
        
        await browser.close()
        
        # Simpan
        if scraped_results:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(scraped_results, f, indent=4)
            print(f"\n✅ DATA SUKSES DISIMPAN KE: {OUTPUT_FILE}")
        else:
            print("\n❌ Masih gagal, kemungkinan IP kena block atau butuh VPN.")

if __name__ == "__main__":
    asyncio.run(scrape_kaa_visible())
