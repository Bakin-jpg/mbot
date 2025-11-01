import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin
import os # Untuk membuat direktori screenshot

async def scrape_kickass_anime():
    """
    Scrape data anime lengkap dari kickass-anime.ru, termasuk URL iframe video untuk SETIAP episode,
    dengan penanganan error yang lebih baik dan log real-time.
    """
    # Buat direktori untuk menyimpan screenshot debugging jika belum ada
    os.makedirs("debug_screenshots", exist_ok=True)

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
            print("Berhasil membuka halaman utama.", flush=True)

            await page.wait_for_selector(".latest-update .row.mt-0 .show-item", timeout=60000)
            print("Bagian 'Latest Update' ditemukan.", flush=True)

            anime_items = await page.query_selector_all(".latest-update .row.mt-0 .show-item")
            print(f"Menemukan {len(anime_items)} item anime terbaru.", flush=True)

            scraped_data = []

            for index, item in enumerate(anime_items):
                print(f"\n--- Memproses Anime #{index + 1} ---", flush=True)
                detail_page = None
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
                    print(f"URL Poster: {poster_url}", flush=True)

                    # Ambil URL detail
                    detail_link_element = await item.query_selector("h2.show-title a")
                    if not detail_link_element:
                        print("Gagal menemukan link judul seri, melewati item ini.", flush=True)
                        continue
                    
                    detail_url_path = await detail_link_element.get_attribute("href")
                    full_detail_url = urljoin(base_url, detail_url_path)
                    
                    # Buka halaman detail
                    detail_page = await context.new_page()
                    await detail_page.goto(full_detail_url, timeout=90000)
                    await detail_page.wait_for_selector(".anime-info-card", timeout=30000)
                    
                    # 1. Selector Judul
                    title_element = await detail_page.query_selector(".anime-info-card .v-card__title span")
                    title = await title_element.inner_text() if title_element else "Judul tidak ditemukan"
                    print(f"Judul Anime: {title}", flush=True)

                    # 2. Selector Sinopsis
                    synopsis_card_title = await detail_page.query_selector("div.v-card__title:has-text('Synopsis')")
                    synopsis = "Sinopsis tidak ditemukan"
                    if synopsis_card_title:
                        parent_card = await synopsis_card_title.query_selector("xpath=..")
                        synopsis_element = await parent_card.query_selector(".text-caption")
                        if synopsis_element:
                            synopsis = await synopsis_element.inner_text()
                    
                    # 3. Selector Genre
                    genre_elements = await detail_page.query_selector_all(".anime-info-card .v-chip--outlined .v-chip__content")
                    all_tags = [await el.inner_text() for el in genre_elements]
                    irrelevant_tags = ['TV', 'PG-13', 'Airing', '2025', '2024', '23 min', '24 min', 'SUB', 'DUB', 'ONA']
                    genres = [tag for tag in all_tags if tag not in irrelevant_tags and not tag.startswith('EP')]

                    # 4. Selector METADATA yang fleksibel
                    metadata_selector = ".anime-info-card .d-flex.mb-3, .anime-info-card .d-flex.mt-2.mb-3"
                    metadata_container = await detail_page.query_selector(metadata_selector)
                    metadata = []
                    if metadata_container:
                        metadata_elements = await metadata_container.query_selector_all(".text-subtitle-2")
                        all_meta_texts = [await el.inner_text() for el in metadata_elements]
                        metadata = [text.strip() for text in all_meta_texts if text and text.strip() != '•']
                    
                    # 5. [PERBAIKAN UTAMA] Extract semua episode dan URL iframe
                    episodes = []
                    print("Mencoba menemukan daftar episode...", flush=True)
                    
                    try:
                        # Tunggu hingga daftar episode muncul. Timeout diperpanjang menjadi 60 detik.
                        await detail_page.wait_for_selector(".episode-list-container", timeout=60000)
                        print("Daftar episode ditemukan. Memproses episode satu per satu.", flush=True)

                        # Dapatkan semua item episode
                        episode_items = await detail_page.query_selector_all(".episode-list-items .episode-item")
                        print(f"Menemukan {len(episode_items)} episode untuk {title}.", flush=True)
                        
                        for ep_index, episode_item in enumerate(episode_items):
                            episode_page = None
                            try:
                                # Dapatkan judul episode
                                episode_title_element = await episode_item.query_selector(".episode-badge .v-chip__content")
                                episode_title = await episode_title_element.inner_text() if episode_title_element else f"Episode {ep_index + 1}"
                                print(f"  -> Memproses {episode_title}...", flush=True)
                                
                                # Dapatkan URL episode
                                episode_link = await episode_item.query_selector("a.v-card.v-card--link")
                                if episode_link:
                                    episode_url_path = await episode_link.get_attribute("href")
                                    episode_url = urljoin(base_url, episode_url_path)
                                    
                                    # Buka halaman episode di halaman baru
                                    episode_page = await context.new_page()
                                    await episode_page.goto(episode_url, timeout=90000)
                                    
                                    # Tunggu sebentar agar JS di halaman episode selesai dimuat
                                    await episode_page.wait_for_timeout(3000)
                                    
                                    # Cari iframe di halaman episode
                                    iframe_element = await episode_page.query_selector("iframe.player")
                                    if iframe_element:
                                        iframe_url = await iframe_element.get_attribute("src")
                                        print(f"     - URL iframe ditemukan: {iframe_url}", flush=True)
                                    else:
                                        print(f"     - URL iframe tidak ditemukan di halaman episode.", flush=True)
                                    
                                    await episode_page.close()
                                
                                episodes.append({
                                    "episode_title": episode_title,
                                    "iframe_url": iframe_url if 'iframe_url' in locals() else "Tidak tersedia"
                                })

                            except Exception as e:
                                print(f"     !!! Gagal memproses {episode_title}: {type(e).__name__}: {e}", flush=True)
                                if episode_page and not episode_page.is_closed():
                                    await episode_page.close()
                                # Lanjut ke episode berikutnya meskipun ada error

                    except Exception as e:
                        # Jika daftar episode tidak ditemukan setelah timeout
                        print(f"!!! Gagal menemukan daftar episode untuk {title} setelah 60 detik. Error: {type(e).__name__}", flush=True)
                        # Ambil screenshot untuk debugging
                        screenshot_path = f"debug_screenshots/failed_anime_{index}_{title.replace(' ', '_')}.png"
                        await detail_page.screenshot(path=screenshot_path)
                        print(f"     - Screenshot disimpan di {screenshot_path} untuk investigasi.", flush=True)
                    
                    anime_info = {
                        "judul": title.strip(),
                        "sinopsis": synopsis.strip(),
                        "genre": genres,
                        "metadata": metadata,
                        "url_poster": poster_url,
                        "episodes": episodes
                    }
                    scraped_data.append(anime_info)
                    await detail_page.close()

                except Exception as e:
                    print(f"!!! Gagal memproses anime #{index + 1}: {type(e).__name__}: {e}", flush=True)
                    if detail_page and not detail_page.is_closed():
                        await detail_page.close()

            print("\n" + "="*50, flush=True)
            print(f"HASIL SCRAPING SELESAI. Total {len(scraped_data)} data berhasil diambil.", flush=True)
            print("="*50, flush=True)
                
            with open('anime_data.json', 'w', encoding='utf-8') as f:
                json.dump(scraped_data, f, ensure_ascii=False, indent=4)
            print("\nData berhasil disimpan ke anime_data.json", flush=True)

        except Exception as e:
            print(f"Terjadi kesalahan fatal: {type(e).__name__}: {e}", flush=True)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_kickass_anime())
