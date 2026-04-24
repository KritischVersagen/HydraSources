#!/bin/sh

set -e

echo "Running all the scrappers..."
python3 scrapers/steamrip.com.py
python3 scrapers/steamunderground.net.py
torify python3 scrapers/erotorrent.ru.py
echo "Finished"

