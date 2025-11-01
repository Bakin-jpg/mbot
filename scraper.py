import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin

async def scrape_kickass_anime():
    """
    Scrape data anime lengkap dari kickass-anime.ru, termasuk URL iframe video,
    dengan selector fleksibel yang dapat menangani tata letak desktop dan mobile.
    """
    async with async_playwright() as p:
        # Menggunakan viewport desktop sebagai default, karena server biasanya begitu
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

            scraped_data = []

            for index, item in enumerate(anime_items):
                print(f"\n--- Memproses Item #{index + 1} ---")
                detail_page = None
                episode_page = None
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
                    
                    # Buka halaman detail
                    detail_page = await context.new_page()
                    await detail_page.goto(full_detail_url, timeout=90000)
                    await detail_page.wait_for_selector(".anime-info-card", timeout=30000)
                    
                    # 1. Selector Judul
                    title_element = await detail_page.query_selector(".anime-info-card .v-card__title span")
                    title = await title_element.inner_text() if title_element else "Judul tidak ditemukan"

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
                    
                    # 5. [TAMBAHAN BARU] Extract URL iframe
                    iframe_url = "Tidak tersedia"
                    
                    # Cari tombol "Watch Now" dan klik untuk membuka halaman episode
                    watch_now_button = await detail_page.query_selector("a.pulse-button.v-btn.v-btn--block.v-btn--is-elevated.v-btn--has-bg.theme--dark.v-size--small.primary")
                    if watch_now_button:
                        # Dapatkan URL dari tombol Watch Now
                        watch_now_href = await watch_now_button.get_attribute("href")
                        if watch_now_href:
                            episode_url = urljoin(base_url, watch_now_href)
                            
                            # Buka halaman episode
                            episode_page = await context.new_page()
                            await episode_page.goto(episode_url, timeout=90000)
                            
                            # Tunggu halaman episode dimuat
                            await episode_page.wait_for_timeout(3000)
                            
                            # Cari iframe di halaman episode
                            iframe_element = await episode_page.query_selector("iframe.player")
                            if iframe_element:
                                iframe_url = await iframe_element.get_attribute("src")
                                print(f"URL iframe ditemukan: {iframe_url}")
                            else:
                                print("URL iframe tidak ditemukan di halaman episode")
                            
                            await episode_page.close()
                    
                    anime_info = {
                        "judul": title.strip(),
                        "sinopsis": synopsis.strip(),
                        "genre": genres,
                        "metadata": metadata,
                        "url_poster": poster_url,
                        "url_iframe": iframe_url  # [TAMBAHAN BARU] Menambahkan URL iframe
                    }
                    scraped_data.append(anime_info)
                    await detail_page.close()

                except Exception as e:
                    print(f"!!! Gagal memproses item #{index + 1}: {type(e).__name__}: {e}")
                    if detail_page and not detail_page.is_closed():
                        await detail_page.close()
                    if episode_page and not episode_page.is_closed():
                        await episode_page.close()

            print("\n" + "="*50)
            print(f"HASIL SCRAPING SELESAI. Total {len(scraped_data)} data berhasil diambil.")
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
