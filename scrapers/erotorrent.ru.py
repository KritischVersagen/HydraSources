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
    "name": "Erotorrent.ru",
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

with Progress(
    SpinnerColumn(),
    BarColumn(),
    TextColumn("Pages [{task.completed}/{task.total}]"),
    TimeElapsedColumn(),
) as page_progress:

    task = page_progress.add_task("pages", total=last_page)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_page, i): i for i in range(1, last_page + 1)}

        for future in as_completed(futures):
            try:
                game_urls.extend(future.result())
            except:
                pass

            page_progress.update(task, advance=1)

# ----------------------
# GAME SCRAPING
# ----------------------

console.print(f"Games found: {len(game_urls)}", style="cyan")

def fetch_game(game):
    return get_game_data(game)

with Progress(
    SpinnerColumn(),
    BarColumn(),
    TextColumn("Games [{task.completed}/{task.total}]"),
    TimeElapsedColumn(),
) as game_progress:

    task = game_progress.add_task("games", total=len(game_urls))

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_game, g) for g in game_urls]

        for future in as_completed(futures):
            try:
                results = future.result()
                for r in results:
                    hydra_source_format["downloads"].append(r)
            except:
                pass

            game_progress.update(task, advance=1)

# ----------------------
# SAVE OUTPUT
# ----------------------

with open("sources/erotorrent.ru_source.json", "w") as f:
    json.dump(hydra_source_format, f, indent=4)

console.print("Done!", style="green")