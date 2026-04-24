import re
import json
import urllib.parse

from threading import Lock
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import cloudscraper

from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

console = Console()

scrapper = cloudscraper.create_scraper()

lock = Lock()

max_retries = 10

hit_404 = False
page_game_data_list = []
hydra_format = {
    "name": "SteamRip.com | Kritisch Rescrape",
    "downloads": []
}

def parse_upload_date(raw: str):
    if not raw:
        return None

    raw = raw.strip().lower()
    now = datetime.now(timezone.utc)

    try:
        match = re.match(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", raw)
        if match:
            value = int(match.group(1))
            unit = match.group(2)

            if unit == "second":
                dt = now - timedelta(seconds=value)
            elif unit == "minute":
                dt = now - timedelta(minutes=value)
            elif unit == "hour":
                dt = now - timedelta(hours=value)
            elif unit == "day":
                dt = now - timedelta(days=value)
            elif unit == "week":
                dt = now - timedelta(weeks=value)
            elif unit == "month":
                dt = now - timedelta(days=value * 30)
            elif unit == "year":
                dt = now - timedelta(days=value * 365)
            else:
                return None

            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        dt = datetime.strptime(raw, "%B %d, %Y")
        dt = dt.replace(tzinfo=timezone.utc)

        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    except:
        return None

def get_page(page:int):
    global page_game_data_list, hit_404
    fail_count = 0
    while True:
        if fail_count >= max_retries:
            console.print(f"Failed to many times while getting page: {page}", style="red", markup=False)
            return
        try:
            console.print(f"Grabbing page: {page}", style="cyan", markup=False)

            params = {
                "s": ""
            }
            res = scrapper.get(f"https://steamrip.com/page/{page}", params=params)
            if res.status_code == 404:
                hit_404 = True
                return
            res.raise_for_status()

            soup = BeautifulSoup(res.content, "html.parser")

            console.print(f"Searching for games in page: {page}", style="cyan", markup=False)
            for game_container in soup.find_all("div", class_="tie-standard"):
                game_url_tag = game_container.find("a", class_="all-over-thumb-link")
                game_name_tag = game_container.find("span", class_="screen-reader-text")
                if game_url_tag and game_name_tag:
                    game_url = game_url_tag.get("href")
                    if game_url:
                        game_name = game_name_tag.text
                        game_url = urllib.parse.urljoin("https://steamrip.com", game_url)
                        with lock:
                            page_game_data_list.append({
                                "url": game_url,
                                "name": game_name
                            })
                        console.print(f"Added game: {game_name} ({game_url})", style="green", markup=False)

            console.print(f"Finished with page: {page}", style="green", markup=False)
            '''
            with open("test.html", "w+") as f:
                f.write(res.text)
            '''
            return
        except Exception as e:
            console.print(f"Had an error on page: {page}\n{e}", style="red", markup=False)
            fail_count += 1

def get_game_data(game_data:dict):
    title = game_data["name"]
    repackLinkSource = game_data["url"]

    fail_count = 0
    while True:
        if fail_count >= max_retries:
            console.print(f"Failed to many times while getting game: {title}", style="red", markup=False)
            return
        try:
            uploadDate = ""
            fileSize = ""
            descriptionHtml = ""
            uris = []

            console.print(f"Getting game page: {title}", style="cyan", markup=False)
            res = scrapper.get(repackLinkSource)
            res.raise_for_status()

            console.print(f"Finding game data: {title}", style="cyan", markup=False)
            soup = BeautifulSoup(res.content, "html.parser")
            post_meta_tag = soup.find_all("div", class_="single-post-meta")[0]
            if post_meta_tag:
                date_tag = post_meta_tag.find("span", class_="date")
                if date_tag:
                    uploadDate = parse_upload_date(date_tag.text)

            for info_list in soup.find_all("div", class_="tie-list-shortcode"):
                for li in info_list.find_all("li"):
                    li_strong = li.find("strong")
                    if li_strong:
                        if "game size" in li_strong.text.lower():
                            fileSize = li.text.split(": ")[-1]

            descriptionHtml = str(soup.find("article", id="the-post"))

            for game_link_tag in soup.find_all("a", class_="shortc-button"):
                game_link = game_link_tag.get("href")
                if game_link:
                    if game_link.startswith("//"):
                        game_link = f"https:{game_link}"
                    uris.append(game_link)

            with lock:
                hydra_format["downloads"].append({
                    "title": title,
                    "fileSize": fileSize,
                    "descriptionHtml": descriptionHtml,
                    "uploadDate": uploadDate,
                    "uris": uris,
                    "repackLinkSource": repackLinkSource
                })

            '''
            with open("test2.html", "w+") as f:
                f.write(res.text)
            '''

            console.print(f"Got game data: {title}", style="green", markup=False)
            return
        except Exception as e:
            console.print(f"Had an error with game: {title}\n{e}", style="red", markup=False)
            fail_count += 1

console.print("Scrapping for repack urls...", style="cyan", markup=False)
cur_page = 1

while True:
    get_page(cur_page)
    if hit_404:
        break
    cur_page += 1

console.print("Scrapped all game urls, now scrapping game data...", style="cyan", markup=False)

with Progress(
    SpinnerColumn(),
    BarColumn(),
    TextColumn("Games [{task.completed}/{task.total}]"),
    TimeElapsedColumn(),
) as game_progress:

    task = game_progress.add_task("games", total=len(page_game_data_list))

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for game in page_game_data_list:
            futures.append(executor.submit(get_game_data, game))

        for future in as_completed(futures):
            future.result()
            game_progress.update(task, advance=1)

console.print(f"Finished scrapping all game data with {len(hydra_format['downloads'])} game stuff.", style="green", markup=False)

with open("sources/steamrip.com_source.json", "w") as f:
    json.dump(hydra_format, f, indent=4)