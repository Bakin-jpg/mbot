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
                    
                    # Fungsi untuk mendapatkan daftar sub/dub yang tersedia dari iframe URL
                    async def get_available_subdub_from_iframe(iframe_src):
                        """Mendapatkan daftar sub/dub yang tersedia dari analisis iframe URL"""
                        subdub_options = []
                        try:
                            if not iframe_src or "krussdomi.com/cat-player/player" not in iframe_src:
                                return ["Japanese"]  # Default
                            
                            parsed_url = urlparse(iframe_src)
                            query_params = parse_qs(parsed_url.query)
                            
                            # Daftar bahasa yang tersedia berdasarkan pattern URL
                            available_languages = {
                                'en-US': 'English',
                                'ja-JP': 'Japanese', 
                                'es-ES': 'Español',
                                'fr-FR': 'Français',
                                'de-DE': 'Deutsch',
                                'zh-CN': 'Chinese',
                                'ko-KR': 'Korean',
                                'pt-BR': 'Portuguese',
                                'ru-RU': 'Russian'
                            }
                            
                            # Jika ada parameter ln, gunakan bahasa tersebut sebagai default
                            current_lang = query_params.get('ln', ['ja-JP'])[0]
                            
                            # Prioritaskan bahasa yang umum tersedia
                            priority_langs = ['Japanese', 'English', 'Español', 'Chinese']
                            
                            for lang in priority_langs:
                                # Cari kode bahasa yang sesuai
                                for code, name in available_languages.items():
                                    if name == lang:
                                        subdub_options.append(name)
                                        break
                            
                            print(f"Sub/Dub tersedia dari iframe analysis: {subdub_options}")
                            return subdub_options
                            
                        except Exception as e:
                            print(f"Gagal analisis iframe URL: {e}")
                            return ["Japanese", "English", "Español"]

                    # Fungsi untuk mengganti sub/dub dengan mengubah parameter URL
                    async def change_subdub_by_url(watch_page, target_subdub, current_iframe_url):
                        """Mengganti sub/dub dengan memodifikasi parameter ln di URL iframe"""
                        try:
                            if not current_iframe_url:
                                return current_iframe_url
                            
                            # Mapping nama bahasa ke kode
                            lang_mapping = {
                                'English': 'en-US',
                                'Japanese': 'ja-JP',
                                'Español': 'es-ES',
                                'Français': 'fr-FR',
                                'Deutsch': 'de-DE',
                                'Chinese': 'zh-CN',
                                'Korean': 'ko-KR',
                                'Portuguese': 'pt-BR',
                                'Russian': 'ru-RU'
                            }
                            
                            target_lang_code = lang_mapping.get(target_subdub, 'ja-JP')
                            
                            # Parse dan modifikasi URL
                            parsed_url = urlparse(current_iframe_url)
                            query_params = parse_qs(parsed_url.query)
                            query_params['ln'] = [target_lang_code]
                            
                            # Bangun URL baru
                            new_query = urlencode(query_params, doseq=True)
                            new_iframe_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{new_query}"
                            
                            # Execute JavaScript untuk mengganti iframe src
                            await watch_page.evaluate(f"""
                                const iframe = document.querySelector('iframe.player');
                                if (iframe) {{
                                    iframe.src = '{new_iframe_url}';
                                }}
                            """)
                            
                            await watch_page.wait_for_timeout(3000)  # Tunggu loading
                            print(f"Berhasil ganti ke: {target_subdub} ({target_lang_code})")
                            return new_iframe_url
                            
                        except Exception as e:
                            print(f"Gagal mengganti sub/dub ke {target_subdub}: {e}")
                            return current_iframe_url

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
                    async def get_iframe_with_fallback(watch_page, episode_number, current_iframe_url):
                        """Mendapatkan iframe dengan fallback ke sub/dub lain jika gagal"""
                        # Dapatkan daftar sub/dub yang tersedia dari iframe URL
                        available_subdub = await get_available_subdub_from_iframe(current_iframe_url)
                        
                        print(f"  Mencoba {len(available_subdub)} sub/dub: {available_subdub}")
                        
                        for subdub in available_subdub:
                            print(f"  Mencoba sub/dub: {subdub}")
                            
                            # Ganti sub/dub dengan mengubah URL
                            new_iframe_url = await change_subdub_by_url(watch_page, subdub, current_iframe_url)
                            
                            # Tunggu iframe loading
                            await watch_page.wait_for_timeout(3000)
                            
                            # Scrape iframe baru
                            iframe_element = await watch_page.query_selector("iframe.player")
                            final_iframe_src = await iframe_element.get_attribute("src") if iframe_element else new_iframe_url
                            
                            # Cek jika iframe valid
                            if await is_iframe_valid(final_iframe_src):
                                print(f"    Iframe valid ditemukan: {final_iframe_src}")
                                return {
                                    "iframe_url": final_iframe_src,
                                    "subdub_used": subdub,
                                    "status": "success"
                                }
                            else:
                                print(f"    Iframe tidak valid untuk {subdub}")
                        
                        # Jika semua sub/dub gagal, return iframe original
                        print(f"  Semua sub/dub gagal untuk episode {episode_number}, menggunakan original")
                        return {
                            "iframe_url": current_iframe_url,
                            "subdub_used": "Original",
                            "status": "partial"
                        }

                    # Scrape iframe player untuk episode saat ini
                    iframe_element = await watch_page.query_selector("iframe.player")
                    current_iframe_url = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                    
                    # Dapatkan iframe dengan fallback sub/dub
                    current_iframe_info = await get_iframe_with_fallback(watch_page, "Current", current_iframe_url)
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
                        
                        # Tentukan batch episode yang akan di-scrape
                        if existing_anime and existing_anime.get('total_episode') == total_episodes:
                            # Jika jumlah episode sama, hanya update 10 episode pertama untuk efisiensi
                            episodes_to_scrape = min(10, total_episodes)
                            print(f"Anime tidak berubah, hanya update {episodes_to_scrape} episode pertama")
                        else:
                            # Jika anime baru atau episode berubah, scrape lebih banyak
                            if total_episodes > 20:
                                episodes_to_scrape = min(10, total_episodes)  # Cicil 10 episode
                                print(f"Episode lebih dari 20, menggunakan metode cicil ({episodes_to_scrape} episode)")
                            else:
                                episodes_to_scrape = min(total_episodes, 10)  # Maksimal 10 episode
                                print(f"Scraping {episodes_to_scrape} episode")
                        
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
                                ep_url = urljoin(base_url, await ep_link.get_attribute("href")) if ep_link else f"{watch_url.rsplit('/', 1)[0]}/ep-{ep_index + 1}"
                                
                                print(f"  - Mengklik episode {ep_number}...")
                                
                                # Klik episode untuk memuat iframe
                                await ep_item.click()
                                await watch_page.wait_for_timeout(3000)  # Tunggu loading
                                
                                # Dapatkan iframe current
                                ep_iframe_element = await watch_page.query_selector("iframe.player")
                                ep_current_iframe = await ep_iframe_element.get_attribute("src") if ep_iframe_element else "Iframe tidak ditemukan"
                                
                                # Dapatkan iframe dengan fallback sub/dub
                                ep_iframe_info = await get_iframe_with_fallback(watch_page, ep_number, ep_current_iframe)
                                
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
                                    "episode_url": f"{watch_url.rsplit('/', 1)[0]}/ep-{ep_index + 1}",
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
                        "scraping_strategy": "cicil" if total_episodes > 20 else "full",
                        "last_updated": asyncio.get_event_loop().time()
                    }
                    
                    # Update atau tambah data baru
                    if existing_anime:
                        # Update data existing
                        existing_anime.update(anime_info)
                        scraped_data.append(existing_anime)
                        print(f"✓ Data {title} diperbarui")
                    else:
                        # Tambah data baru
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
