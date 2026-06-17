#!/usr/bin/env python3
"""Build a local archive with the largest cities per country."""

from __future__ import annotations

import json
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "top_cities.json"
GEONAMES_CITIES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
GEONAMES_COUNTRIES_URL = "https://download.geonames.org/export/dump/countryInfo.txt"
DEFAULT_LIMIT = 10
CITY_FEATURE_CODES = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC"}


def clean_list(values, limit=None):
    seen = set()
    cleaned = []
    for value in values:
        if not value:
            continue
        for item in str(value).split(","):
            text = item.strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                cleaned.append(text)
                if limit and len(cleaned) >= limit:
                    return cleaned
    return cleaned


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "maptoposter-top-cities-cache/1.0 (local development)"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def load_countries() -> dict[str, dict]:
    countries = {}
    content = fetch_bytes(GEONAMES_COUNTRIES_URL).decode("utf-8")
    for line in content.splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 17:
            continue
        iso2, iso3, country_name, capital = fields[0], fields[1], fields[4], fields[5]
        aliases = clean_list([iso2, iso3, country_name, capital])
        if iso2 == "US":
            aliases.extend(["USA", "United States", "United States of America", "America"])
        if iso2 == "GB":
            aliases.extend(["UK", "United Kingdom", "Great Britain"])
        countries[iso2] = {
            "country": country_name,
            "country_codes": clean_list([iso2, iso3]),
            "country_aliases": clean_list(aliases),
        }
    return countries


def main() -> None:
    countries = load_countries()
    cities_by_country = defaultdict(list)
    cities_zip = fetch_bytes(GEONAMES_CITIES_URL)

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "cities15000.zip"
        zip_path.write_bytes(cities_zip)
        with zipfile.ZipFile(zip_path) as archive:
            with archive.open("cities15000.txt") as file:
                for raw_line in file:
                    fields = raw_line.decode("utf-8").rstrip("\n").split("\t")
                    if len(fields) < 19:
                        continue
                    (
                        geoname_id,
                        name,
                        ascii_name,
                        alternate_names,
                        latitude,
                        longitude,
                        feature_class,
                        feature_code,
                        country_code,
                        *_rest,
                    ) = fields
                    population = int(fields[14] or 0)
                    if (
                        feature_class != "P"
                        or feature_code not in CITY_FEATURE_CODES
                        or population <= 0
                        or country_code not in countries
                    ):
                        continue

                    cities_by_country[country_code].append(
                        {
                            "geoname_id": geoname_id,
                            "city": name,
                            "city_aliases": clean_list([name, ascii_name, alternate_names], limit=30),
                            "latitude": float(latitude),
                            "longitude": float(longitude),
                            "population": population,
                        }
                    )

    records = []
    for country_code, cities in cities_by_country.items():
        country = countries[country_code]
        for rank, city in enumerate(
            sorted(cities, key=lambda item: item["population"], reverse=True)[:DEFAULT_LIMIT],
            start=1,
        ):
            records.append(
                {
                    **country,
                    **city,
                    "rank_in_country": rank,
                }
            )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "cities": GEONAMES_CITIES_URL,
            "countries": GEONAMES_COUNTRIES_URL,
            "limit_per_country": DEFAULT_LIMIT,
        },
        "cities": sorted(records, key=lambda item: (item["country"].casefold(), item["rank_in_country"])),
    }

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} city records to {OUTPUT}")


if __name__ == "__main__":
    main()
