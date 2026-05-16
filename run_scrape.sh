#!/bin/sh

set -e

echo "Running all the scrappers..."
python3 scrapers/steamrip.com.py
python3 scrapers/steamunderground.net.py
python3 scrapers/erotorrent.ru.py
python3 scrapers/gamebounty.world.py
echo "Finished"

