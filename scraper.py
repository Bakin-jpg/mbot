import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
import re
import os

async def scrape_kickass_anime():
    """
    Scrape data anime lengkap dari kickass-anime.ru, termasuk iframe setiap episode dengan dukungan sub/dub.
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
            if os.path.exists('anime_data_with_all_iframes.json'):
                with open('anime_data_with_all_iframes.json', 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                print(f"Data existing ditemukan: {len(existing_data)} anime")

            scraped_data = []

            for index, item in enumerate(anime_items[:3]):  # Batasi untuk testing
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
                    await detail_page.goto(full_detail_url, timeout=90000)
                    await detail_page.wait_for_selector(".anime-info-card", timeout=30000)
                    
                    # Scrape informasi dasar
                    title_element = await detail_page.query_selector(".anime-info-card .v-card__title span")
                    title = await title_element.inner_text() if title_element else "Judul tidak ditemukan"

                    # Scrape sinopsis
                    synopsis_card_title = await detail_page.query_selector("div.v-card__title:has-text('Synopsis')")
                    synopsis = "Sinopsis tidak ditemukan"
                    if synopsis_card_title:
                        parent_card = await synopsis_card_title.query_selector("xpath=..")
                        synopsis_element = await parent_card.query_selector(".text-caption")
                        if synopsis_element:
                            synopsis = await synopsis_element.inner_text()
                    
                    # Scrape genre
                    genre_elements = await detail_page.query_selector_all(".anime-info-card .v-chip--outlined .v-chip__content")
                    all_tags = [await el.inner_text() for el in genre_elements]
                    irrelevant_tags = ['TV', 'PG-13', 'Airing', '2025', '2024', '23 min', '24 min', 'SUB', 'DUB', 'ONA']
                    genres = [tag for tag in all_tags if tag not in irrelevant_tags and not tag.startswith('EP')]

                    # Scrape metadata
                    metadata_selector = ".anime-info-card .d-flex.mb-3, .anime-info-card .d-flex.mt-2.mb-3"
                    metadata_container = await detail_page.query_selector(metadata_selector)
                    metadata = []
                    if metadata_container:
                        metadata_elements = await metadata_container.query_selector_all(".text-subtitle-2")
                        all_meta_texts = [await el.inner_text() for el in metadata_elements]
                        metadata = [text.strip() for text in all_meta_texts if text and text.strip() != 'â€¢']

                    # Cari tombol "Watch Now" dan ambil URL watch
                    watch_button = await detail_page.query_selector('a.v-btn[href*="/ep-"]')
                    watch_url = None
                    if watch_button:
                        watch_url_path = await watch_button.get_attribute("href")
                        watch_url = urljoin(base_url, watch_url_path)
                        print(f"URL Watch ditemukan: {watch_url}")
                    else:
                        print("Tombol Watch Now tidak ditemukan")
                        await detail_page.close()
                        continue

                    # Buka halaman watch untuk scrape iframe dan episode
                    watch_page = await context.new_page()
                    await watch_page.goto(watch_url, timeout=90000)
                    await watch_page.wait_for_selector(".player-container", timeout=30000)
                    
                    # Fungsi untuk mendapatkan daftar sub/dub yang tersedia DARI DROPDOWN
                    async def get_available_subdub_from_dropdown(watch_page):
                        """Mendapatkan daftar sub/dub yang tersedia dengan MEMBACA DROPDOWN"""
                        subdub_options = []
                        try:
                            # Cari dropdown sub/dub dengan berbagai selector
                            dropdown_selectors = [
                                "//div[contains(@class, 'v-select')]//div[contains(@class, 'v-select__selections')]",
                                ".v-select .v-select__selections",
                                "//label[contains(text(), 'Sub/Dub')]/following-sibling::div//div[contains(@class, 'v-select__selections')]"
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
                                print("Dropdown Sub/Dub tidak ditemukan")
                                return []
                            
                            # Klik dropdown untuk membuka opsi
                            await dropdown.click()
                            await watch_page.wait_for_timeout(2000)
                            
                            # Baca opsi-opsi yang tersedia
                            option_selectors = [
                                ".v-list-item .v-list-item__title",
                                ".v-select-list .v-list-item__content",
                                "//div[contains(@class, 'v-list-item')]//div[contains(@class, 'v-list-item__title')]"
                            ]
                            
                            for selector in option_selectors:
                                if selector.startswith("//"):
                                    option_elements = await watch_page.query_selector_all(f"xpath={selector}")
                                else:
                                    option_elements = await watch_page.query_selector_all(selector)
                                
                                if option_elements:
                                    for option in option_elements:
                                        option_text = await option.inner_text()
                                        if option_text and option_text.strip():
                                            subdub_options.append(option_text.strip())
                                    
                                    if subdub_options:
                                        break
                            
                            # Tutup dropdown
                            await watch_page.keyboard.press("Escape")
                            await watch_page.wait_for_timeout(1000)
                            
                            print(f"Sub/Dub tersedia dari dropdown: {subdub_options}")
                            return subdub_options
                            
                        except Exception as e:
                            print(f"Gagal membaca dropdown sub/dub: {e}")
                            return []

                    # Fungsi untuk mengganti sub/dub DENGAN MEMILIH DARI DROPDOWN
                    async def change_subdub_from_dropdown(watch_page, target_subdub):
                        """Mengganti sub/dub dengan MEMILIH dari dropdown"""
                        try:
                            # Cari dropdown
                            dropdown_selectors = [
                                "//div[contains(@class, 'v-select')]//div[contains(@class, 'v-select__selections')]",
                                ".v-select .v-select__selections"
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
                                f"//div[contains(@class, 'v-list-item')]//div[contains(text(), '{target_subdub}')]",
                                f".v-list-item:has-text('{target_subdub}')"
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
                                print(f"✗ Opsi {target_subdub} tidak ditemukan")
                                await watch_page.keyboard.press("Escape")
                                return False
                                
                        except Exception as e:
                            print(f"Gagal mengganti sub/dub ke {target_subdub}: {e}")
                            return False

                    # Fungsi untuk mengecek iframe valid
                    async def is_iframe_valid(iframe_src):
                        """Mengecek apakah iframe valid (tidak kosong dan tidak error)"""
                        if not iframe_src or iframe_src in ["Iframe tidak ditemukan", "Iframe tidak tersedia"]:
                            return False
                        
                        # Cek pattern iframe yang valid
                        valid_patterns = [
                            "krussdomi.com/cat-player/player",
                            "vidstream",
                            "type=hls",
                            "cat-player/player"
                        ]
                        
                        return any(pattern in iframe_src for pattern in valid_patterns)

                    # Fungsi untuk mendapatkan iframe dengan sub/dub fallback
                    async def get_iframe_with_fallback(watch_page, episode_number):
                        """Mendapatkan iframe dengan fallback ke sub/dub lain jika gagal"""
                        # Dapatkan daftar sub/dub yang tersedia DARI DROPDOWN
                        available_subdub = await get_available_subdub_from_dropdown(watch_page)
                        
                        # Jika tidak ada dropdown, langsung ambil iframe current
                        if not available_subdub:
                            print("  Tidak ada pilihan sub/dub, menggunakan iframe default")
                            iframe_element = await watch_page.query_selector("iframe.player")
                            current_iframe = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                            return {
                                "iframe_url": current_iframe,
                                "subdub_used": "Default",
                                "status": "success"
                            }
                        
                        print(f"  Mencoba {len(available_subdub)} sub/dub: {available_subdub}")
                        
                        # Coba setiap sub/dub yang tersedia
                        for subdub in available_subdub:
                            print(f"  Mencoba sub/dub: {subdub}")
                            
                            # Ganti sub/dub jika bukan yang pertama
                            if subdub != available_subdub[0]:
                                success = await change_subdub_from_dropdown(watch_page, subdub)
                                if not success:
                                    print(f"    Gagal mengganti ke {subdub}, lanjut...")
                                    continue
                            
                            # Tunggu iframe loading
                            await watch_page.wait_for_timeout(4000)
                            
                            # Scrape iframe
                            iframe_element = await watch_page.query_selector("iframe.player")
                            iframe_src = await iframe_element.get_attribute("src") if iframe_element else None
                            
                            # Cek jika iframe valid
                            if await is_iframe_valid(iframe_src):
                                print(f"    ✓ Iframe valid ditemukan untuk {subdub}")
                                return {
                                    "iframe_url": iframe_src,
                                    "subdub_used": subdub,
                                    "status": "success"
                                }
                            else:
                                print(f"    ✗ Iframe tidak valid untuk {subdub}")
                        
                        # Jika semua gagal, coba iframe default
                        print(f"  Semua sub/dub gagal untuk episode {episode_number}, mencoba default")
                        iframe_element = await watch_page.query_selector("iframe.player")
                        final_iframe = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak tersedia"
                        
                        return {
                            "iframe_url": final_iframe,
                            "subdub_used": "Default",
                            "status": "partial" if await is_iframe_valid(final_iframe) else "failed"
                        }

                    # Scrape iframe player untuk episode saat ini dengan fallback
                    current_iframe_info = await get_iframe_with_fallback(watch_page, "Current")
                    iframe_src = current_iframe_info["iframe_url"]
                    print(f"URL Iframe episode saat ini: {iframe_src}")

                    # Scrape informasi episode saat ini
                    episode_info = {}
                    try:
                        # Judul episode
                        episode_title_element = await watch_page.query_selector(".v-card__title h1.text-h6")
                        episode_title = await episode_title_element.inner_text() if episode_title_element else "Judul episode tidak ditemukan"
                        
                        # Nomor episode
                        episode_number_element = await watch_page.query_selector(".v-card__title .text-overline")
                        episode_number = await episode_number_element.inner_text() if episode_number_element else "Episode number tidak ditemukan"
                        
                        episode_info = {
                            "judul_episode": episode_title,
                            "nomor_episode": episode_number,
                            "iframe_url": iframe_src,
                            "subdub_used": current_iframe_info["subdub_used"]
                        }
                    except Exception as e:
                        print(f"Gagal scrape info episode: {e}")

                    # Scrape daftar episode dengan iframe masing-masing
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
                                
                                # Klik episode untuk memuat iframe
                                await ep_item.click()
                                await watch_page.wait_for_timeout(3000)
                                
                                # Dapatkan iframe dengan fallback sub/dub
                                ep_iframe_info = await get_iframe_with_fallback(watch_page, ep_number)
                                
                                episodes_data.append({
                                    "episode_number": ep_number,
                                    "episode_url": ep_url,
                                    "iframe_url": ep_iframe_info["iframe_url"],
                                    "subdub_used": ep_iframe_info["subdub_used"],
                                    "status": ep_iframe_info["status"]
                                })
                                
                                print(f"    Iframe: {ep_iframe_info['iframe_url']}")
                                print(f"    Sub/Dub: {ep_iframe_info['subdub_used']}")
                                print(f"    Status: {ep_iframe_info['status']}")
                                
                            except Exception as ep_e:
                                print(f"Gagal memproses episode {ep_index}: {type(ep_e).__name__}: {ep_e}")
                                episodes_data.append({
                                    "episode_number": f"EP {ep_index + 1}",
                                    "episode_url": None,
                                    "iframe_url": "Gagal diambil",
                                    "subdub_used": "None",
                                    "status": "error"
                                })
                                continue
                                
                    except Exception as e:
                        print(f"Gagal scrape daftar episode: {e}")

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
                        "available_subdub": await get_available_subdub_from_dropdown(watch_page)  # Simpan pilihan sub/dub yang tersedia
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
