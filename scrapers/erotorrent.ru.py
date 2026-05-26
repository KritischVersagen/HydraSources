# Don't judge, but this was reformated with ChatGPT, the original concept script was made by me.

import json
import time
import random
import cloudscraper

from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

# ======================
# INIT
# ======================

scraper = cloudscraper.create_scraper()
console = Console()

retries = 5

game_urls = []

hydra_source_format = {
    "name": "Erotorrent.ru | Kritisch Rescrape",
    "downloads": []
}

# ======================
# DATE PARSER
# ======================

def parse_upload_date(raw: str):
    if not raw:
        return None

    raw = raw.strip().lower()

    now = datetime.now(timezone.utc)

    try:
        # -------------------------
        # Russian relative dates
        # -------------------------
        if "вчера" in raw:  # yesterday
            time_part = raw.split(",")[-1].strip()
            t = datetime.strptime(time_part, "%H:%M").time()
            dt = datetime.combine(
                (now - timedelta(days=1)).date(),
                t,
                tzinfo=timezone.utc
            )
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        if "сегодня" in raw:  # today
            time_part = raw.split(",")[-1].strip()
            t = datetime.strptime(time_part, "%H:%M").time()
            dt = datetime.combine(now.date(), t, tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # -------------------------
        # Normal format: 12-04-2023, 08:15
        # -------------------------
        dt = datetime.strptime(raw, "%d-%m-%Y, %H:%M")
        dt = dt.replace(tzinfo=timezone.utc)

        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    except:
        return None

# ======================
# SEARCH PAGES
# ======================

def search(page: int):
    fail_count = 0

    while True:
        if fail_count > retries:
            return []

        try:
            res = scraper.get(f"https://erotorrent.ru/page/{page}/", timeout=10)
            soup = BeautifulSoup(res.content, "html.parser")

            games = []

            for game_thing in soup.find_all("div", class_="short_news"):
                page_url = game_thing.find("a").get("href", "")
                poster = game_thing.find("img", class_="poster").get("src", "")
                title = game_thing.find("div", class_="news_title").find("span").text

                games.append({
                    "title": title,
                    "page_url": page_url,
                    "poster": poster
                })

            return games

        except Exception:
            fail_count += 1
            time.sleep(random.uniform(1, 5))

# ======================
# GAME DATA SCRAPER
# ======================

def get_game_data(start_data: dict):
    fail_count = 0
    url = start_data["page_url"]

    while True:
        if fail_count > retries:
            return []

        try:
            res = scraper.get(url, timeout=10)
            soup = BeautifulSoup(res.content, "html.parser")

            # ---- upload date (FIXED + SAFE) ----
            upload_date = None
            right_info = soup.find("div", class_="right_full_info")

            if right_info:
                date_tag = right_info.find("div", class_="left_full_stat_2")
                if date_tag:
                    upload_date = parse_upload_date(date_tag.text)

            # ---- downloads ----
            all_game_data = []

            for download_data in soup.find_all("div", class_="one_one"):
                left_top = download_data.find("div", class_="file_left_top")
                right_top = download_data.find("div", class_="file_right_top")

                if not left_top or not right_top:
                    continue

                version_tag = left_top.find("span", class_=["file_left_1", "bold_1"])
                size_tag = right_top.find("span", class_="file_left_1")
                link_tag = right_top.find("a")

                version = version_tag.text if version_tag else "Unknown"
                size = size_tag.text if size_tag else "Unknown"
                download_url = link_tag.get("href", "") if link_tag else ""

                descriptionHtml = download_data.find("div", class_="faq_inst")

                all_game_data.append({
                    "version": version,
                    "size": size,
                    "download_url": download_url,
                    "description": str(descriptionHtml)
                })

            formatted = []

            for g in all_game_data:
                if start_data["title"] != "" and g["download_url"] != "":
                    formatted.append({
                        "title": f'{start_data["title"]} [{g["version"]}]',
                        "fileSize": g["size"].split(": ")[-1],
                        "descriptionHtml": g["description"],
                        "uploadDate": upload_date,
                        "uris": [g["download_url"]],
                        "repackLinkSource": url
                    })

            return formatted

        except Exception:
            fail_count += 1
            time.sleep(random.uniform(1, 5))

# ======================
# FIND LAST PAGE
# ======================

def find_last_page():
    fail_count = 0

    while True:
        if fail_count > retries:
            raise Exception("Failed to get last page")

        try:
            res = scraper.get("https://erotorrent.ru/", timeout=10)
            soup = BeautifulSoup(res.content, "html.parser")

            return int(
                soup.find("div", class_="pages")
                .find_all("a")[-1]
                .text
            )

        except Exception:
            fail_count += 1
            time.sleep(random.uniform(1, 5))

# ======================
# RUN
# ======================

console.print("Getting last page...", style="cyan")
last_page = find_last_page()
console.print(f"Pages found: {last_page}", style="green")

# ----------------------
# PAGE SCRAPING
# ----------------------

def fetch_page(i):
    return search(i)

total = last_page

console.print(f"Fetching {total} pages...", style="cyan")

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {
        executor.submit(fetch_page, i): i
        for i in range(1, last_page + 1)
    }

    completed = 0

    for future in as_completed(futures):
        page_num = futures[future]

        try:
            results = future.result()

            if results:
                game_urls.extend(results)

            completed += 1

            console.print(
                f"[{completed}/{total}] "
                f"Page {page_num} complete "
                f"({len(results) if results else 0} games)",
                style="green"
            )

        except Exception as e:
            console.print(f"::warning::Page {page_num} failed: {e}", style="red")

# ----------------------
# GAME SCRAPING
# ----------------------

console.print(f"Games found: {len(game_urls)}", style="cyan")

total = len(game_urls)

console.print(f"Processing {total} games...", style="cyan")

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {
        executor.submit(get_game_data, game): game
        for game in game_urls
    }

    completed = 0

    for future in as_completed(futures):
        game = futures[future]

        try:
            future.result()
            completed += 1
            console.print(f"[{completed}/{total}] Finished: {game}", style="green")
        except Exception as e:
            console.print(f"Failed: {game} -> {e}", style="red")

# ----------------------
# SAVE OUTPUT
# ----------------------

if len(hydra_format["downloads"]) >= 50:
    with open("sources/erotorrent.ru_source.json", "w") as f:
        json.dump(hydra_source_format, f, indent=4)
else:
    console.print(f"Didn't fully scrape so not saving...", style="green", markup=False)

console.print("Done!", style="green")