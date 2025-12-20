import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
import re
import os

async def scrape_kickass_anime():
    """
    Scrape data anime lengkap dari kickass-anime.ru, termasuk m3u8/hls setiap episode dengan dukungan sub/dub.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        try:
            base_url = "https://kickass-anime.ru/"
            await page.goto(base_url, timeout=90000, wait_until="domcontentloaded")
            print("Berhasil membuka halaman utama.")

            await page.wait_for_selector(".latest-update .row.mt-0 .show-item", timeout=60000)
            print("Bagian 'Latest Update' ditemukan.")

            anime_items = await page.query_selector_all(".latest-update .row.mt-0 .show-item")
            print(f"Menemukan {len(anime_items)} item anime terbaru.")

            # Load existing data jika ada
            existing_data = []
            if os.path.exists('anime_data.json'):
                with open('anime_data.json', 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                print(f"Data existing ditemukan: {len(existing_data)} anime")

            scraped_data = []

            for index, item in enumerate(anime_items[:36]):  # Batasi untuk testing
                print(f"\n--- Memproses Item #{index + 1} ---")
                detail_page = None
                watch_page = None
                
                try:
                    # Ambil URL Poster dari halaman utama
                    await item.scroll_into_view_if_needed()
                    poster_url = "Tidak tersedia"
                    for attempt in range(5):
                        poster_div = await item.query_selector(".v-image__image--cover")
                        if poster_div:
                            poster_style = await poster_div.get_attribute("style")
                            if poster_style and 'url("' in poster_style:
                                parts = poster_style.split('url("')
                                if len(parts) > 1:
                                    poster_url_path = parts[1].split('")')[0]
                                    poster_url = urljoin(base_url, poster_url_path)
                                    break
                        await page.wait_for_timeout(300)
                    print(f"URL Poster: {poster_url}")

                    # Ambil URL detail
                    detail_link_element = await item.query_selector("h2.show-title a")
                    if not detail_link_element:
                        print("Gagal menemukan link judul seri, melewati item ini.")
                        continue
                    
                    detail_url_path = await detail_link_element.get_attribute("href")
                    full_detail_url = urljoin(base_url, detail_url_path)
                    
                    # Cek apakah anime sudah ada di data existing
                    existing_anime = None
                    for anime in existing_data:
                        if anime.get('url_detail') == full_detail_url:
                            existing_anime = anime
                            print(f"Anime sudah ada di data existing: {anime.get('judul')}")
                            break

                    # Buka halaman detail
                    detail_page = await context.new_page()
                    await detail_page.goto(full_detail_url, timeout=90000, wait_until="domcontentloaded")
                    
                    # Tunggu lebih lama untuk memastikan halaman dimuat
                    await detail_page.wait_for_timeout(5000)
                    
                    # Ambil screenshot untuk debugging
                    try:
                        screenshot_path = f"debug_detail_{index + 1}.png"
                        await detail_page.screenshot(path=screenshot_path, full_page=False)
                        print(f"✓ Screenshot halaman detail disimpan: {screenshot_path}")
                    except:
                        pass
                    
                    # Scrape informasi dasar - menggunakan selector baru
                    title_element = await detail_page.query_selector("h1.text-h6")
                    title = await title_element.inner_text() if title_element else "Judul tidak ditemukan"
                    
                    # Jika judul tidak ditemukan, coba selector alternatif
                    if title == "Judul tidak ditemukan":
                        title_element = await detail_page.query_selector(".v-card__title span")
                        title = await title_element.inner_text() if title_element else "Judul tidak ditemukan"
                    
                    print(f"Judul: {title}")

                    # Scrape sinopsis - menggunakan selector baru
                    synopsis = "Sinopsis tidak ditemukan"
                    try:
                        synopsis_elements = await detail_page.query_selector_all(".text-caption")
                        if synopsis_elements:
                            # Cari elemen sinopsis yang paling panjang
                            for elem in synopsis_elements:
                                text = await elem.inner_text()
                                if len(text) > 20:  # Asumsi sinopsis lebih panjang dari 20 karakter
                                    synopsis = text
                                    break
                    except:
                        pass
                    
                    # Scrape genre - menggunakan selector baru
                    genres = []
                    try:
                        genre_elements = await detail_page.query_selector_all(".v-chip__content")
                        all_tags = [await el.inner_text() for el in genre_elements]
                        irrelevant_tags = ['TV', 'PG-13', 'Airing', '2025', '2024', '23 min', '24 min', 'SUB', 'DUB', 'ONA', 
                                          'R', 'PG', 'G', 'Finished', 'Movie', 'OVA', 'Special']
                        genres = [tag for tag in all_tags if tag not in irrelevant_tags and not tag.startswith('EP')]
                    except:
                        pass

                    # Scrape metadata - menggunakan selector baru
                    metadata = []
                    try:
                        metadata_elements = await detail_page.query_selector_all(".text-subtitle-2")
                        all_meta_texts = [await el.inner_text() for el in metadata_elements]
                        metadata = [text.strip() for text in all_meta_texts if text and text.strip() != '•']
                    except:
                        pass

                    # FUNGSI TEMUKAN TOMBOL WATCH NOW
                    async def find_watch_button(page):
                        """Mencari tombol Watch Now dengan berbagai cara"""
                        
                        selectors = [
                            # Selector spesifik dari HTML yang Anda berikan
                            'a.pulse-button.v-btn--block[href*="/ep-"]',
                            'a.pulse-button[href*="/ep-"]',
                            
                            # Selector umum
                            'a[href*="/ep-"]:has-text("Watch Now")',
                            'a.v-btn[href*="/ep-"]',
                            'button:has-text("Watch Now")',
                            '//button[contains(text(), "Watch Now")]',
                            '//a[contains(text(), "Watch Now")]',
                            
                            # Selector berdasarkan class
                            '.v-btn.primary:has-text("Watch Now")',
                            'a[href*="/ep-"][class*="v-btn"]',
                            
                            # XPath selector
                            '//a[contains(@class, "pulse-button")]',
                            '//*[contains(text(), "Watch Now") and @href]',
                            
                            # Selector lebih umum
                            '//a[contains(@href, "/ep-")]',
                            'a[href*="/ep-"]'
                        ]
                        
                        for selector in selectors:
                            try:
                                print(f"  Mencari dengan selector: {selector}")
                                if selector.startswith('//'):
                                    element = await page.query_selector(f'xpath={selector}')
                                else:
                                    element = await page.query_selector(selector)
                                
                                if element:
                                    is_visible = await element.is_visible()
                                    if is_visible:
                                        print(f"  ✓ Tombol ditemukan dengan selector: {selector}")
                                        return element
                            except Exception as e:
                                continue
                        
                        # Jika tidak ditemukan, cari semua elemen dengan teks "Watch Now"
                        try:
                            all_elements = await page.query_selector_all('*')
                            for element in all_elements:
                                try:
                                    text = await element.text_content()
                                    if text and "Watch Now" in text:
                                        is_visible = await element.is_visible()
                                        if is_visible:
                                            print(f"  ✓ Tombol ditemukan berdasarkan teks: Watch Now")
                                            return element
                                except:
                                    continue
                        except:
                            pass
                        
                        return None

                    # Cari tombol "Watch Now" dan ambil URL watch
                    print("Mencari tombol Watch Now...")
                    watch_button = await find_watch_button(detail_page)

                    watch_url = None
                    if watch_button:
                        try:
                            # Coba dapatkan href dari elemen
                            watch_url_path = await watch_button.get_attribute("href")
                            if watch_url_path:
                                watch_url = urljoin(base_url, watch_url_path)
                                print(f"✓ URL Watch ditemukan: {watch_url}")
                            else:
                                # Jika tidak ada href, mungkin ini button bukan link
                                print("⚠️ Elemen tidak memiliki href, cari link episode di sekitar")
                                
                                # Cari link episode di parent atau sibling
                                parent = await watch_button.query_selector('xpath=..')
                                if parent:
                                    parent_link = await parent.query_selector('a[href*="/ep-"]')
                                    if parent_link:
                                        watch_url_path = await parent_link.get_attribute("href")
                                        watch_url = urljoin(base_url, watch_url_path)
                                        print(f"✓ URL Watch ditemukan di parent: {watch_url}")
                                
                        except Exception as e:
                            print(f"❌ Gagal mendapatkan URL: {e}")
                            watch_url = None
                    else:
                        print("❌ Tombol Watch Now tidak ditemukan")
                        
                        # Coba cari link episode langsung di halaman
                        print("Mencari link episode langsung...")
                        episode_links = await detail_page.query_selector_all('a[href*="/ep-"]')
                        if episode_links:
                            for link in episode_links:
                                href = await link.get_attribute("href")
                                print(f"  Link episode ditemukan: {href}")
                            watch_url_path = await episode_links[0].get_attribute("href")
                            watch_url = urljoin(base_url, watch_url_path)
                            print(f"✓ Menggunakan link episode pertama: {watch_url}")
                        else:
                            print("❌ Tidak ada link episode ditemukan")
                            await detail_page.close()
                            continue

                    # Buka halaman watch untuk scrape m3u8/hls dan episode
                    watch_page = await context.new_page()
                    
                    # Fungsi untuk menangkap network request dan mendapatkan URL m3u8
                    async def setup_network_sniffer(page):
                        m3u8_urls = []
                        
                        # Fungsi untuk menangkap response
                        async def handle_response(response):
                            url = response.url
                            if ".m3u8" in url:
                                if url not in m3u8_urls:
                                    m3u8_urls.append(url)
                                    print(f"  ✓ M3U8 ditemukan: {url}")
                        
                        # Daftarkan listener untuk response
                        page.on("response", handle_response)
                        return m3u8_urls

                    # Fungsi untuk mendapatkan daftar sub/dub yang tersedia
                    async def get_available_subdub_from_dropdown(watch_page):
                        """Mendapatkan daftar sub/dub yang tersedia dengan MEMBACA DROPDOWN YANG BENAR"""
                        subdub_options = []
                        try:
                            # Cari dropdown sub/dub yang tepat - di episode list section
                            dropdown_selectors = [
                                # Selector untuk dropdown di episode list (bukan menu navigasi)
                                "//div[contains(@class, 'episode-list')]//div[contains(@class, 'v-select')]",
                                "//div[contains(@class, 'v-card__title')]//div[contains(@class, 'v-select')]",
                                ".episode-list .v-select",
                                "//label[contains(text(), 'Sub/Dub')]/ancestor::div[contains(@class, 'v-select')]"
                            ]
                            
                            dropdown = None
                            for selector in dropdown_selectors:
                                if selector.startswith("//"):
                                    dropdown = await watch_page.query_selector(f"xpath={selector}")
                                else:
                                    dropdown = await watch_page.query_selector(selector)
                                if dropdown:
                                    print(f"Dropdown ditemukan dengan selector: {selector}")
                                    break
                            
                            if not dropdown:
                                print("Dropdown Sub/Dub tidak ditemukan di episode list")
                                return []
                            
                            # Klik dropdown untuk membuka opsi
                            await dropdown.click()
                            await watch_page.wait_for_timeout(2000)
                            
                            # Baca opsi-opsi yang tersedia dari menu dropdown yang terbuka
                            option_selectors = [
                                "//div[contains(@class, 'v-menu__content')]//div[contains(@class, 'v-list-item__title')]",
                                ".v-menu__content .v-list-item .v-list-item__title",
                                "//div[contains(@class, 'v-list-item__title')]"
                            ]
                            
                            for selector in option_selectors:
                                if selector.startswith("//"):
                                    option_elements = await watch_page.query_selector_all(f"xpath={selector}")
                                else:
                                    option_elements = await watch_page.query_selector_all(selector)
                                
                                if option_elements:
                                    print(f"Found {len(option_elements)} options with selector: {selector}")
                                    for option in option_elements:
                                        option_text = await option.inner_text()
                                        if option_text and option_text.strip():
                                            # Filter hanya opsi yang berhubungan dengan bahasa/sub/dub
                                            if any(keyword in option_text.lower() for keyword in ['japanese', 'english', 'chinese', 'español', 'sub', 'dub']):
                                                subdub_options.append(option_text.strip())
                                    
                                    if subdub_options:
                                        break
                            
                            # Jika tidak ada opsi yang ditemukan, coba cara lain
                            if not subdub_options:
                                # Coba baca dari elemen yang sedang aktif
                                active_option = await watch_page.query_selector("//div[contains(@class, 'v-select__selections')]//div[contains(@class, 'v-select__selection')]")
                                if active_option:
                                    active_text = await active_option.inner_text()
                                    if active_text and active_text.strip():
                                        subdub_options = [active_text.strip()]
                                        print(f"Hanya menemukan 1 opsi: {active_text}")
                            
                            # === PERUBAHAN PENTING: PRIORITAS CHINESE ===
                            chinese_options = [subdub for subdub in subdub_options if 'chinese' in subdub.lower()]
                            if chinese_options:
                                print(f"  🎯 CHINESE DETECTED - Filter hanya Chinese: {chinese_options}")
                                subdub_options = chinese_options
                            # === END PERUBAHAN ===
                            
                            # Tutup dropdown
                            await watch_page.keyboard.press("Escape")
                            await watch_page.wait_for_timeout(1000)
                            
                            print(f"Sub/Dub tersedia dari dropdown: {subdub_options}")
                            return subdub_options
                            
                        except Exception as e:
                            print(f"Gagal membaca dropdown sub/dub: {e}")
                            return []

                    # Fungsi untuk mengganti sub/dub
                    async def change_subdub_from_dropdown(watch_page, target_subdub):
                        """Mengganti sub/dub dengan MEMILIH dari dropdown yang benar"""
                        try:
                            # Cari dropdown yang tepat
                            dropdown_selectors = [
                                "//div[contains(@class, 'episode-list')]//div[contains(@class, 'v-select')]",
                                ".episode-list .v-select"
                            ]
                            
                            dropdown = None
                            for selector in dropdown_selectors:
                                if selector.startswith("//"):
                                    dropdown = await watch_page.query_selector(f"xpath={selector}")
                                else:
                                    dropdown = await watch_page.query_selector(selector)
                                if dropdown:
                                    break
                            
                            if not dropdown:
                                print("Dropdown tidak ditemukan untuk mengganti sub/dub")
                                return False
                            
                            # Buka dropdown
                            await dropdown.click()
                            await watch_page.wait_for_timeout(2000)
                            
                            # Cari dan klik opsi yang diinginkan
                            option_selectors = [
                                f"//div[contains(@class, 'v-menu__content')]//div[contains(@class, 'v-list-item__title') and contains(text(), '{target_subdub}')]",
                                f".v-menu__content .v-list-item:has-text('{target_subdub}')"
                            ]
                            
                            target_option = None
                            for selector in option_selectors:
                                if selector.startswith("//"):
                                    target_option = await watch_page.query_selector(f"xpath={selector}")
                                else:
                                    target_option = await watch_page.query_selector(selector)
                                if target_option:
                                    break
                            
                            if target_option:
                                await target_option.click()
                                await watch_page.wait_for_timeout(4000)  # Tunggu loading lebih lama
                                print(f"✓ Berhasil ganti ke: {target_subdub}")
                                return True
                            else:
                                print(f"✗ Opsi {target_subdub} tidak ditemukan dalam dropdown")
                                await watch_page.keyboard.press("Escape")
                                return False
                                
                        except Exception as e:
                            print(f"Gagal mengganti sub/dub ke {target_subdub}: {e}")
                            return False

                    # Fungsi untuk mengecek m3u8 valid
                    async def is_m3u8_valid(m3u8_url):
                        """Mengecek apakah m3u8 valid (tidak kosong dan tidak error)"""
                        if not m3u8_url or m3u8_url in ["M3U8 tidak ditemukan", "M3U8 tidak tersedia"]:
                            return False
                        
                        # Cek pattern m3u8 yang valid
                        valid_patterns = [
                            "krussdomi.com/manifest",
                            "hls.krussdomi.com",
                            "manifest",
                            ".m3u8"
                        ]
                        
                        return any(pattern in m3u8_url for pattern in valid_patterns)

                    # Fungsi untuk mendapatkan semua m3u8 untuk semua sub/dub yang tersedia
                    async def get_all_subdub_m3u8(watch_page, episode_number):
                        """Mendapatkan semua m3u8 untuk semua sub/dub yang tersedia"""
                        # Setup network sniffer untuk menangkap m3u8
                        m3u8_urls = await setup_network_sniffer(watch_page)
                        
                        # Dapatkan daftar sub/dub yang tersedia
                        available_subdub = await get_available_subdub_from_dropdown(watch_page)
                        
                        # === PERUBAHAN PENTING: PRIORITAS CHINESE ===
                        chinese_options = [subdub for subdub in available_subdub if 'chinese' in subdub.lower()]
                        if chinese_options:
                            print(f"  🎯 DETECTED CHINESE CONTENT - Hanya ambil Chinese: {chinese_options}")
                            available_subdub = chinese_options  # Hanya proses Chinese saja
                        # === END PERUBAHAN ===
                        
                        if not available_subdub:
                            print("  Tidak ada pilihan sub/dub, menggunakan m3u8 default")
                            return {
                                "m3u8_url": m3u8_urls[0] if m3u8_urls else "M3U8 tidak ditemukan",
                                "subdub_used": "Default",
                                "status": "success",
                                "all_subdub_m3u8": {"Default": m3u8_urls[0] if m3u8_urls else "M3U8 tidak ditemukan"}
                            }
                        
                        print(f"  Mengambil m3u8 untuk {len(available_subdub)} sub/dub: {available_subdub}")
                        
                        all_m3u8 = {}
                        current_subdub = available_subdub[0]
                        
                        # Tunggu beberapa saat untuk memastikan m3u8 sudah tercapture
                        await watch_page.wait_for_timeout(5000)
                        
                        # Simpan m3u8 original terlebih dahulu
                        original_m3u8 = m3u8_urls[0] if m3u8_urls else "M3U8 tidak ditemukan"
                        all_m3u8[current_subdub] = original_m3u8
                        
                        # Coba setiap sub/dub yang tersedia (kecuali yang pertama)
                        for i, subdub in enumerate(available_subdub):
                            # Skip yang pertama karena itu yang sedang aktif
                            if i == 0:
                                continue
                                
                            print(f"  Mengambil m3u8 untuk: {subdub}")
                            
                            # Ganti sub/dub
                            success = await change_subdub_from_dropdown(watch_page, subdub)
                            if not success:
                                print(f"    Gagal mengganti ke {subdub}, lanjut...")
                                continue
                            
                            # Tunggu m3u8 loading
                            await watch_page.wait_for_timeout(5000)
                            
                            # Cek jika m3u8 valid
                            if m3u8_urls and await is_m3u8_valid(m3u8_urls[-1]):
                                print(f"    ✓ M3U8 valid ditemukan untuk {subdub}")
                                all_m3u8[subdub] = m3u8_urls[-1]
                            else:
                                print(f"    ✗ M3U8 tidak valid untuk {subdub}")
                                all_m3u8[subdub] = "M3U8 tidak valid"
                        
                        # Generate semua URL alternatif berdasarkan m3u8 yang berhasil
                        all_subdub_urls = {}
                        for subdub_name, m3u8_url in all_m3u8.items():
                            if await is_m3u8_valid(m3u8_url):
                                all_subdub_urls[subdub_name] = m3u8_url
                                
                                # Hanya generate versi lain jika bukan Chinese content
                                if "ln=" in m3u8_url and not any('chinese' in subdub_name.lower() for subdub_name in all_m3u8.keys()):
                                    base_m3u8 = m3u8_url
                                    # Generate Japanese version
                                    jp_url = base_m3u8.replace("ln=en-US", "ln=ja-JP").replace("ln=es-ES", "ln=ja-JP")
                                    if "Japanese" not in all_subdub_urls and "Japanese" in available_subdub:
                                        all_subdub_urls["Japanese (SUB)"] = jp_url
                                    
                                    # Generate English version  
                                    en_url = base_m3u8.replace("ln=ja-JP", "ln=en-US").replace("ln=es-ES", "ln=en-US")
                                    if "English" not in all_subdub_urls and "English" in available_subdub:
                                        all_subdub_urls["English (DUB)"] = en_url
                                    
                                    # Generate Spanish version
                                    es_url = base_m3u8.replace("ln=ja-JP", "ln=es-ES").replace("ln=en-US", "ln=es-ES")
                                    if "EspaÃ±ol" not in all_subdub_urls and any("EspaÃ±ol" in s for s in available_subdub):
                                        all_subdub_urls["EspaÃ±ol (EspaÃ±a)"] = es_url
                        
                        # Kembali ke subdub original
                        if len(available_subdub) > 1:
                            await change_subdub_from_dropdown(watch_page, available_subdub[0])
                        
                        # Gunakan m3u8 yang paling valid sebagai primary
                        primary_m3u8 = original_m3u8
                        primary_subdub = current_subdub
                        for subdub, m3u8_url in all_m3u8.items():
                            if await is_m3u8_valid(m3u8_url):
                                primary_m3u8 = m3u8_url
                                primary_subdub = subdub
                                break
                        
                        return {
                            "m3u8_url": primary_m3u8,
                            "subdub_used": primary_subdub,
                            "status": "success",
                            "all_subdub_m3u8": all_subdub_urls
                        }

                    # Buka halaman watch
                    await watch_page.goto(watch_url, timeout=90000, wait_until="domcontentloaded")
                    
                    # Tunggu beberapa saat untuk memastikan halaman dimuat
                    await watch_page.wait_for_timeout(5000)
                    
                    # Scrape m3u8 player untuk episode saat ini dengan semua sub/dub
                    current_m3u8_info = await get_all_subdub_m3u8(watch_page, "Current")
                    m3u8_url = current_m3u8_info["m3u8_url"]
                    print(f"URL M3U8 episode saat ini: {m3u8_url}")
                    print(f"Semua m3u8 tersedia: {list(current_m3u8_info.get('all_subdub_m3u8', {}).keys())}")

                    # Scrape informasi episode saat ini
                    episode_info = {}
                    try:
                        # Judul episode
                        episode_title_element = await watch_page.query_selector("h1.text-h6")
                        episode_title = await episode_title_element.inner_text() if episode_title_element else "Judul episode tidak ditemukan"
                        
                        # Nomor episode
                        episode_number_element = await watch_page.query_selector(".text-overline")
                        episode_number = await episode_number_element.inner_text() if episode_number_element else "Episode number tidak ditemukan"
                        
                        episode_info = {
                            "judul_episode": episode_title,
                            "nomor_episode": episode_number,
                            "m3u8_url": m3u8_url,
                            "subdub_used": current_m3u8_info["subdub_used"],
                            "all_subdub_m3u8": current_m3u8_info.get("all_subdub_m3u8", {})
                        }
                    except Exception as e:
                        print(f"Gagal scrape info episode: {e}")

                    # Scrape daftar episode dengan m3u8 masing-masing
                    episodes_data = []
                    try:
                        # Tunggu elemen episode list muncul
                        await watch_page.wait_for_selector(".episode-item", timeout=30000)
                        
                        # Dapatkan jumlah episode terlebih dahulu
                        episode_items = await watch_page.query_selector_all(".episode-item")
                        total_episodes = len(episode_items)
                        print(f"Menemukan {total_episodes} episode")
                        
                        # Tentukan batch episode yang akan di-scrape (cicil 10 episode)
                        episodes_to_scrape = min(10, total_episodes)
                        print(f"Scraping {episodes_to_scrape} episode (cicil)")
                        
                        # Process episodes
                        for ep_index in range(episodes_to_scrape):
                            try:
                                # Dapatkan ulang elemen episode setiap iterasi
                                episode_items = await watch_page.query_selector_all(".episode-item")
                                if ep_index >= len(episode_items):
                                    break
                                    
                                ep_item = episode_items[ep_index]
                                
                                # Nomor episode
                                ep_badge = await ep_item.query_selector(".episode-badge .v-chip__content")
                                ep_number = await ep_badge.inner_text() if ep_badge else f"EP {ep_index + 1}"
                                
                                # URL episode
                                ep_link = await ep_item.query_selector(".v-card--link")
                                ep_url = urljoin(base_url, await ep_link.get_attribute("href")) if ep_link else None
                                
                                print(f"  - Mengklik episode {ep_number}...")
                                
                                # Klik episode untuk memuat m3u8
                                await ep_item.click()
                                await watch_page.wait_for_timeout(3000)
                                
                                # Dapatkan semua m3u8 untuk semua sub/dub
                                ep_m3u8_info = await get_all_subdub_m3u8(watch_page, ep_number)
                                
                                episodes_data.append({
                                    "episode_number": ep_number,
                                    "episode_url": ep_url,
                                    "m3u8_url": ep_m3u8_info["m3u8_url"],
                                    "subdub_used": ep_m3u8_info["subdub_used"],
                                    "status": ep_m3u8_info["status"],
                                    "all_subdub_m3u8": ep_m3u8_info.get("all_subdub_m3u8", {})
                                })
                                
                                print(f"    M3U8: {ep_m3u8_info['m3u8_url']}")
                                print(f"    Sub/Dub: {ep_m3u8_info['subdub_used']}")
                                print(f"    Semua m3u8: {list(ep_m3u8_info.get('all_subdub_m3u8', {}).keys())}")
                                
                            except Exception as ep_e:
                                print(f"Gagal memproses episode {ep_index}: {type(ep_e).__name__}: {ep_e}")
                                episodes_data.append({
                                    "episode_number": f"EP {ep_index + 1}",
                                    "episode_url": None,
                                    "m3u8_url": "Gagal diambil",
                                    "subdub_used": "None",
                                    "status": "error",
                                    "all_subdub_m3u8": {}
                                })
                                continue
                                
                    except Exception as e:
                        print(f"Gagal scrape daftar episode: {e}")
                        total_episodes = 0

                    # Dapatkan semua pilihan sub/dub yang tersedia
                    available_subdub = await get_available_subdub_from_dropdown(watch_page)
                    
                    anime_info = {
                        "judul": title.strip(),
                        "sinopsis": synopsis.strip(),
                        "genre": genres,
                        "metadata": metadata,
                        "url_poster": poster_url,
                        "url_detail": full_detail_url,
                        "url_watch": watch_url,
                        "episode_saat_ini": episode_info,
                        "semua_episode": episodes_data,
                        "total_episode": total_episodes,
                        "scraping_strategy": "cicil",
                        "last_updated": asyncio.get_event_loop().time(),
                        "available_subdub": available_subdub
                    }
                    
                    # Update atau tambah data baru
                    if existing_anime:
                        existing_anime.update(anime_info)
                        scraped_data.append(existing_anime)
                        print(f"✓ Data {title} diperbarui")
                    else:
                        scraped_data.append(anime_info)
                        print(f"✓ Data {title} ditambahkan baru")
                    
                    # Tutup halaman
                    if watch_page and not watch_page.is_closed():
                        await watch_page.close()
                    if detail_page and not detail_page.is_closed():
                        await detail_page.close()

                except Exception as e:
                    print(f"!!! Gagal memproses item #{index + 1}: {type(e).__name__}: {e}")
                    if watch_page and not watch_page.is_closed():
                        await watch_page.close()
                    if detail_page and not detail_page.is_closed():
                        await detail_page.close()

            # Gabungkan data baru dengan data existing yang tidak di-update
            updated_urls = [anime['url_detail'] for anime in scraped_data]
            for existing_anime in existing_data:
                if existing_anime['url_detail'] not in updated_urls:
                    scraped_data.append(existing_anime)

            print("\n" + "="*50)
            print(f"HASIL SCRAPING SELESAI. Total {len(scraped_data)} data berhasil diambil/diperbarui.")
            print("="*50)
                
            with open('anime_data.json', 'w', encoding='utf-8') as f:
                json.dump(scraped_data, f, ensure_ascii=False, indent=4)
            print("\nData berhasil disimpan ke anime_data.json")

        except Exception as e:
            print(f"Terjadi kesalahan fatal: {type(e).__name__}: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_kickass_anime())
