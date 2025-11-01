import asyncio
from playwright.async_api import async_playwright
import json
from urllib.parse import urljoin
import re

async def scrape_kickass_anime():
    """
    Scrape data anime lengkap dari kickass-anime.ru, termasuk iframe setiap episode.
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

            scraped_data = []

            for index, item in enumerate(anime_items):
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
                    
                    # Scrape iframe player untuk episode saat ini
                    iframe_element = await watch_page.query_selector("iframe.player")
                    iframe_src = await iframe_element.get_attribute("src") if iframe_element else "Iframe tidak ditemukan"
                    print(f"URL Iframe: {iframe_src}")

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
                            "iframe_url": iframe_src
                        }
                    except Exception as e:
                        print(f"Gagal scrape info episode: {e}")

                    # Scrape daftar episode dengan iframe masing-masing
                    episodes_data = []
                    try:
                        # Tunggu elemen episode list muncul
                        await watch_page.wait_for_selector(".episode-item", timeout=30000)
                        
                        episode_items = await watch_page.query_selector_all(".episode-item")
                        print(f"Menemukan {len(episode_items)} episode")
                        
                        for ep_index, ep_item in enumerate(episode_items):
                            try:
                                # URL episode
                                ep_link = await ep_item.query_selector(".v-card--link")
                                ep_url = await ep_link.get_attribute("href") if ep_link else None
                                
                                # Nomor episode
                                ep_badge = await ep_item.query_selector(".episode-badge .v-chip__content")
                                ep_number = await ep_badge.inner_text() if ep_badge else f"EP {ep_index + 1}"
                                
                                # Jika episode memiliki URL, buka untuk ambil iframe
                                ep_iframe = "Iframe tidak tersedia"
                                if ep_url:
                                    full_ep_url = urljoin(base_url, ep_url)
                                    
                                    # Buka halaman episode untuk ambil iframe
                                    ep_page = await context.new_page()
                                    try:
                                        await ep_page.goto(full_ep_url, timeout=60000)
                                        await ep_page.wait_for_selector(".player-container", timeout=20000)
                                        
                                        # Scrape iframe dari episode ini
                                        ep_iframe_element = await ep_page.query_selector("iframe.player")
                                        if ep_iframe_element:
                                            ep_iframe = await ep_iframe_element.get_attribute("src")
                                        
                                        await ep_page.close()
                                    except Exception as ep_page_error:
                                        print(f"Gagal membuka halaman episode {ep_number}: {ep_page_error}")
                                        if not ep_page.is_closed():
                                            await ep_page.close()
                                        ep_iframe = "Gagal mengambil iframe"
                                
                                episodes_data.append({
                                    "episode_number": ep_number,
                                    "episode_url": ep_url,
                                    "iframe_url": ep_iframe
                                })
                                
                                print(f"  - Episode {ep_number}: {ep_iframe}")
                                
                            except Exception as ep_e:
                                print(f"Gagal memproses episode {ep_index}: {ep_e}")
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
                        "semua_episode": episodes_data
                    }
                    
                    scraped_data.append(anime_info)
                    
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

            print("\n" + "="*50)
            print(f"HASIL SCRAPING SELESAI. Total {len(scraped_data)} data berhasil diambil.")
            print("="*50)
                
            with open('anime_data_with_all_iframes.json', 'w', encoding='utf-8') as f:
                json.dump(scraped_data, f, ensure_ascii=False, indent=4)
            print("\nData berhasil disimpan ke anime_data_with_all_iframes.json")

        except Exception as e:
            print(f"Terjadi kesalahan fatal: {type(e).__name__}: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_kickass_anime())
