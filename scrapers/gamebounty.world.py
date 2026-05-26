import re
import json
import time
import random
import urllib.parse

from threading import Lock
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import njsparser
import cloudscraper

from bs4 import BeautifulSoup
from rich.console import Console
from ratelimit import limits, sleep_and_retry
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn


console = Console()
scrapper = cloudscraper.create_scraper(
    delay=8,
    interpreter="nodejs"
)
lock = Lock()
max_retries = 10
hit_404 = False
page_game_data_list = []

MAX_CALLS_PER_MINUTE = 25
PERIOD_SECONDS = 5

hydra_format = {
    "name": "GameBounty | Kritisch Rescrape",
    "downloads": []
}

@sleep_and_retry
@limits(calls=MAX_CALLS_PER_MINUTE, period=PERIOD_SECONDS)
def rate_limited_get(url: str, timeout=35):
    res = scrapper.get(url, timeout=timeout)
    return res

def random_delay(min_sec=2.0, max_sec=6.0):
    dl = round(random.uniform(min_sec, max_sec), 3)
    console.print(f"Waiting {dl} seconds")
    time.sleep(dl)

def is_rate_limited(game_dater: dict) -> bool:
    if not game_dater:
        return True

    container = game_dater.get("container", {})

    if container.get("error", "").lower() == "rate limit":
        return True

    if container.get("success") is False:
        return True

    data = container.get("data")
    if not data or not isinstance(data, dict):
        return True

    required_fields = ["mirrors", "size_human"]
    if any(key not in data for key in required_fields):
        return True

    return False

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
                "page": page,
                "adult": "show"
            }
            res = scrapper.get(f"https://gamebounty.world/", params=params)
            if res.status_code == 404:
                hit_404 = True
                return
            res.raise_for_status()
            soup = BeautifulSoup(res.content, "html.parser")
            console.print(f"Searching for games in page: {page}", style="cyan", markup=False)
            check = soup.find_all("a", class_="capsule-root")
            if not check:
                hit_404 = True
                return
            for game_container in check:
                game_url_tag = game_container
                game_container_info_tag = game_container.find("div", class_="capsule-info")
                if game_url_tag and game_container_info_tag:
                    game_name_tag = game_container_info_tag.find("p")
                    if game_name_tag:
                        game_url = game_url_tag.get("href")
                        if game_url:
                            game_name = game_name_tag.text
                            game_url = urllib.parse.urljoin("https://gamebounty.world", game_url)
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

def split_url(url: str):
    return [part for part in url.split("/") if part.strip()]

def get_game_urls(download_url:str, title:str):
    fail_count = 0
    while True:
        if fail_count >= max_retries:
            console.print(f"Failed to many times while getting game: {title}", style="red", markup=False)
            return
        try:
            uris = []
            res = scrapper.get(download_url)
            if res.status_code == 404:
                return []
            res.raise_for_status()
            fd = njsparser.BeautifulFD(res.text)

            game_dater = {}

            for data in fd.find_iter([njsparser.T.Data]):
                if data.content and "appid" in str(data.content).lower():
                    game_dater = data.content
                    break

            if not game_dater:
                raise Exception(f"Failed to parse f.push string:\n{fd}")

            if is_rate_limited(game_dater):
                raise Exception("Rate limit detected in payload")

            for mirror in game_dater["container"].get("data", {}).get("mirrors", []):
                uris.append(mirror["links"][0]["url"])

            return uris
        except Exception as e:
            console.print(f"Had an error with game: {title}\n{e}", style="red", markup=False)
            fail_count += 1
            if "rate limit" in str(e).lower():
                random_delay(15, 35)
            else:
                random_delay(4, 10)


def get_game_data(game_data: dict):
    title = game_data["name"]
    repackLinkSource = urllib.parse.unquote(game_data["url"])
    fail_count = 0

    while fail_count < max_retries:
        try:
            res = rate_limited_get(repackLinkSource)
            if res.status_code == 404:
                return
            res.raise_for_status()
            fd = njsparser.BeautifulFD(res.text)

            game_dater = {}
            for data in fd.find_iter([njsparser.T.Data]):
                if data.content and "appid" in str(data.content).lower():
                    game_dater_raw = data.content
                    game_dater_post = game_dater_raw.get("post")
                    if game_dater_post:
                        game_dater = game_dater_post
                        break

            if not game_dater:
                raise Exception("Failed to find game data in flight payload")

            if is_rate_limited(game_dater):
                raise Exception("Rate limit detected in payload")

            version = game_dater["version"]
            uploadDate = game_dater["created_at"]
            fileSize = game_dater["container"]["data"]["size_human"]
            descriptionHtml = game_dater["mini_description"]

            uris = []
            for mirror in game_dater["container"].get("data", {}).get("mirrors", []):
                links = mirror.get("links", [])
                if links:
                    uris.append(links[0]["url"])

            if not uris:
                download_url = f"https://gamebounty.world/download/{split_url(repackLinkSource)[-1]}"
                uris = get_game_urls(download_url, title)
                if not uris:
                    return

            with lock:
                hydra_format["downloads"].append({
                    "title": f"{title} {version}".strip(),
                    "fileSize": fileSize,
                    "descriptionHtml": descriptionHtml,
                    "uploadDate": uploadDate,
                    "uris": uris,
                    "repackLinkSource": repackLinkSource
                })

            return  # Success

        except Exception as e:
            fail_count += 1
            console.print(f"Error on {title} (attempt {fail_count}): {e}", style="red")

            if "rate limit" in str(e).lower():
                random_delay(15, 300)
            else:
                random_delay(4, 10)

    console.print(f"Failed after {max_retries} attempts: {title}", style="red")


console.print("Scrapping for repack urls...", style="cyan", markup=False)

cur_page = 1

while True:
    get_page(cur_page)
    if hit_404:
        break
    cur_page += 1
    #random_delay(1.5, 3.5)

console.print("Scrapped all game urls, now scrapping game data...", style="cyan", markup=False)

total = len(page_game_data_list)

console.print(f"Processing {total} games...", style="cyan")

with ThreadPoolExecutor(max_workers=3) as executor:
    futures = {
        executor.submit(get_game_data, game): game
        for game in page_game_data_list
    }

    completed = 0
    for future in as_completed(futures):
        game = futures[future]
        try:
            future.result()
            completed += 1
            console.print(f"[{completed}/{total}] Finished: {game['name']}", style="green")
        except Exception as e:
            console.print(f"Failed: {game['name']} -> {e}", style="red")

        if completed % 25 == 0:
            random_delay(1, 3)

console.print(f"Finished scrapping all game data with {len(hydra_format['downloads'])}/{len(page_game_data_list)} game stuff.", style="green", markup=False)

if len(hydra_format["downloads"]) >= 100:
    with open("sources/gamebounty.world_source.json", "w") as f:
        json.dump(hydra_format, f, indent=4)
else:
    console.print(f"Didn't fully scrape so not saving...", style="green", markup=False)