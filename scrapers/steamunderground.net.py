import re
import json
import threading

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import cloudscraper

from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

console = Console()
scrapper = cloudscraper.create_scraper()

max_retries = 10

page_game_data_list = []

lock = threading.Lock()

hydra_format = {
    "name": "SteamUnderground.net | Kritisch Rescrape",
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

def get_games():
    fail_count = 0
    while True:
        if fail_count >= max_retries:
            console.print(f"Failed to many times while getting games...", style="red", markup=False)
            return
        try:
            console.print(f"Grabbing games...", style="cyan", markup=False)

            params = {
                "s": ""
            }
            res = scrapper.get(f"https://steamunderground.net/a-to-z-games/", params=params)
            res.raise_for_status()

            soup = BeautifulSoup(res.content, "html.parser")

            console.print(f"Searching for games in page...", style="cyan", markup=False)

            game_container = soup.find("div", class_="post-content")
            if game_container:
                for game in game_container.find_all("li"):
                    game_tag = game.find("a")
                    if game_tag:
                        game_url = game_tag.get("href")
                        if game_url:
                            game_name = game_tag.text
                            with lock:
                                page_game_data_list.append({
                                    "url": game_url,
                                    "name": game_name
                                })
                            console.print(f"Added game: {game_name} ({game_url})", style="green", markup=False)

            console.print(f"Finished with getting games", style="green", markup=False)

            '''
            with open("test.html", "w+") as f:
                f.write(res.text)
            '''

            return
        except Exception as e:
            console.print(f"Had an error while getting games:\n{e}", style="red", markup=False)
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

            #console.print(f"Getting game page: {title}", style="cyan", markup=False)
            res = scrapper.get(repackLinkSource)
            if res.status_code == 404:
                return
            res.raise_for_status()

            #console.print(f"Finding game data: {title}", style="cyan", markup=False)
            soup = BeautifulSoup(res.content, "html.parser")
            for post_meta_tag in soup.find_all("div", class_="meta"):
                if post_meta_tag.find("div", class_="comments"):
                    date_tag = post_meta_tag.find("div", class_="post-date")
                    if date_tag:
                        uploadDate = parse_upload_date(date_tag.text)

            for info_list in soup.find_all("div", class_="article-content"):
                for li in info_list.find_all("li"):
                    li_strong = li.find("strong")
                    if li_strong:
                        if "storage:" == li_strong.text.lower():
                            fileSizeRaw = li.text.replace("\xa0", " ")

                            match = re.search(r'(\d+(?:\.\d+)?\+?)\s*(kb|mb|gb|tb)\b', fileSizeRaw, re.IGNORECASE)

                            if match:
                                fileSize = f"{match.group(1)} {match.group(2).upper()}"
                            else:
                                #print(title)
                                fileSize = "N/A"

            descriptionHtml = str(soup.find("div", class_="article-content"))

            for game_link_tag in soup.find_all("a", class_="enjoy-css"):
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

            #console.print(f"Got game data: {title}", style="green", markup=False)
            return
        except Exception as e:
            console.print(f"Had an error with game: {title}\n{e}", style="red", markup=False)
            fail_count += 1

console.print("Scrapping for repack urls...", style="cyan", markup=False)
cur_page = 1

get_games()

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

console.print(f"Finished scrapping all game data with {len(hydra_format['downloads'])}/{len(page_game_data_list)} game stuff.", style="green", markup=False)

with open("sources/steamunderground.net_source.json", "w") as f:
    json.dump(hydra_format, f, indent=4)