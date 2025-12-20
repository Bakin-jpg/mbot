import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin

# --- KONFIGURASI ---
BASE_URL = "https://kickass-anime.ru/"
OUTPUT_FILE = "anime_data_lengkap.json"

async def scrape_kickass_auto():
    async with async_playwright() as p:
        # Browser setting biar dikira user asli (PENTING buat bypass proteksi)
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            locale="en-US"
        )
        
        # 1. BUKA HOMEPAGE
        page = await context.new_page()
        print(f"🚀 Membuka {BASE_URL} ...")
        try:
            await page.goto(BASE_URL, timeout=60000, wait_until="domcontentloaded")
            
            # Tunggu list anime muncul (berdasarkan inspect element lu: class "latest-update")
            await page.wait_for_selector(".latest-update .show-item", timeout=30000)
            print("✅ Halaman utama terbuka. Membaca daftar anime...")
        except Exception as e:
            print(f"❌ Gagal buka homepage: {e}")
            await browser.close()
            return

        # 2. AMBIL LIST URL EPISODE DARI HALAMAN DEPAN
        # Selector ini ngambil link <a href="..."> di dalam .show-item
        anime_elements = await page.query_selector_all(".latest-update .show-item a.v-card")
        
        tasks_data = []
        for el in anime_elements:
            href = await el.get_attribute("href")
            if href:
                full_url = urljoin(BASE_URL, href)
                tasks_data.append(full_url)
        
        print(f"📦 Ditemukan {len(tasks_data)} episode terbaru untuk diproses.\n")
        
        scraped_results = []

        # 3. LOOPING PROSES SETIAP EPISODE
        # Kita batasi scrape 10 anime dulu biar gak kelamaan nungguin resultnya (bisa lu ubah)
        for index, ep_url in enumerate(tasks_data[:10]): 
            print(f"🎬 [{index+1}/{len(tasks_data)}] Memproses: {ep_url}")
            
            # Buka tab baru untuk setiap episode biar bersih
            ep_page = await context.new_page()
            
            # --- TEKNIK SNIFFING M3U8 (INI INTI NYA) ---
            m3u8_found = None
            
            async def handle_request(request):
                nonlocal m3u8_found
                url = request.url
                # Kita cari URL yang mengandung .m3u8 DAN master/manifest
                # Ini pattern krussdomi yang lu kasih: https://hls.krussdomi.com/.../master.m3u8
                if ".m3u8" in url and ("master" in url or "manifest" in url):
                    print(f"    ⚡ DAPAT LINK: {url}")
                    m3u8_found = url

            # Pasang kuping di jaringan
            ep_page.on("request", handle_request)

            try:
                await ep_page.goto(ep_url, timeout=60000, wait_until="domcontentloaded")
                
                # Tunggu variabel window.KAA muncul (ini data rahasia webnya)
                # Kita ambil judul & episode dari situ biar akurat 100%
                try:
                    await ep_page.wait_for_function("() => window.KAA !== undefined", timeout=15000)
                    metadata = await ep_page.evaluate("""() => {
                        try {
                            const d = window.KAA.data[0].episode;
                            return {
                                judul: d.show_slug.replace(/-/g, ' ').toUpperCase(),
                                episode: "EP " + d.episode_string,
                                poster: d.poster.hq,
                                sinopsis: d.synopsis
                            }
                        } catch(e) { return null; }
                    }""")
                except:
                    print("    ⚠️ Metadata JS timeout, pakai fallback HTML...")
                    metadata = None

                # Fallback kalo ambil data dari JS gagal (ambil dari HTML biasa)
                if not metadata:
                    title_el = await ep_page.query_selector("h1.text-h6")
                    ep_el = await ep_page.query_selector(".text-overline")
                    metadata = {
                        "judul": await title_el.inner_text() if title_el else "Unknown Anime",
                        "episode": await ep_el.inner_text() if ep_el else "Ep ?",
                        "poster": "",
                        "sinopsis": ""
                    }

                # Tunggu player loading & request m3u8 keluar
                # Kita tunggu max 10 detik
                for _ in range(20):
                    if m3u8_found: break
                    await ep_page.wait_for_timeout(500)
                
                # Kalau belum dapet, coba scroll atau klik play (kadang player lazy load)
                if not m3u8_found:
                    # Coba cari iframe player dan scroll ke sana
                    player_frame = await ep_page.query_selector("iframe.player")
                    if player_frame:
                        await player_frame.scroll_into_view_if_needed()
                        await ep_page.wait_for_timeout(2000)

                # Simpan data kalau sukses
                if m3u8_found:
                    scraped_results.append({
                        "judul": metadata['judul'],
                        "episode": metadata['episode'],
                        "url_halaman": ep_url,
                        "url_stream_m3u8": m3u8_found, # <--- INI LINK HLS NYA
                        "poster": metadata['poster'],
                        "sinopsis": metadata['sinopsis']
                    })
                    print("    ✅ Data tersimpan.")
                else:
                    print("    ❌ Gagal dapat link stream (Server timeout/mati).")

            except Exception as e:
                print(f"    ❌ Error: {e}")
            
            finally:
                await ep_page.close()
                # Remove listener gak perlu explicit karena page di close
        
        await browser.close()

        # Simpan hasil akhir ke JSON
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(scraped_results, f, indent=4, ensure_ascii=False)
        
        print("\n" + "="*50)
        print(f"SELESAI. {len(scraped_results)} Anime berhasil diambil.")
        print(f"Cek file: {OUTPUT_FILE}")
        print("="*50)

if __name__ == "__main__":
    asyncio.run(scrape_kickass_auto())
