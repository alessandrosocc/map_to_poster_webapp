#!/usr/bin/env python3
"""Warm OSMnx cache for top cities from the local archive."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")

import create_map_poster as poster  # noqa: E402


def normalize(value: str) -> str:
    return poster.normalize_place_name(value)


def matching_cities(country: str | None, limit: int, all_countries: bool):
    wanted_country = normalize(country or "")
    grouped = {}
    for record in poster.load_top_cities_archive():
        aliases = record.get("country_aliases") or [record.get("country", "")]
        country_matches = all_countries or wanted_country in {normalize(item) for item in aliases}
        if not country_matches:
            continue
        grouped.setdefault(record["country"], []).append(record)

    for country_name in sorted(grouped):
        for record in sorted(grouped[country_name], key=lambda item: item["rank_in_country"])[:limit]:
            yield record


def warm_city(record, distance: int, width: float, height: float) -> None:
    point = (float(record["latitude"]), float(record["longitude"]))
    compensated_dist = distance * (max(height, width) / min(height, width)) / 4
    print(f"warming {record['city']}, {record['country']} ({point[0]}, {point[1]})")
    poster.fetch_graph(point, compensated_dist)
    poster.fetch_features(
        point,
        compensated_dist,
        tags={"natural": ["water", "bay", "strait"], "waterway": "riverbank"},
        name="water",
    )
    poster.fetch_features(
        point,
        compensated_dist,
        tags={"leisure": "park", "landuse": "grass"},
        name="parks",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm map data cache for top cities.")
    parser.add_argument("--country", help="Country name or ISO code, e.g. USA, Italy, France")
    parser.add_argument("--all-countries", action="store_true", help="Warm every country in the archive")
    parser.add_argument("--limit", type=int, default=10, help="Cities per country to warm")
    parser.add_argument("--distance", type=int, default=18000, help="Poster map radius in meters")
    parser.add_argument("--width", type=float, default=12, help="Poster width in inches")
    parser.add_argument("--height", type=float, default=16, help="Poster height in inches")
    args = parser.parse_args()

    if not args.all_countries and not args.country:
        parser.error("Pass --country or explicitly pass --all-countries")

    cities = list(matching_cities(args.country, args.limit, args.all_countries))
    if not cities:
        raise SystemExit("No matching cities found. Refresh data/top_cities.json first.")

    print(f"warming cache for {len(cities)} city/cities")
    for record in cities:
        warm_city(record, args.distance, args.width, args.height)
    print("cache warm complete")


if __name__ == "__main__":
    main()
