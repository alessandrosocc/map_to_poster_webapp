#!/usr/bin/env python3
"""Build a local capitals archive used to avoid repeated geocoding."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "capitals.json"
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_QUERY = """
SELECT ?country ?countryLabel ?countryAltLabel ?capital ?capitalLabel ?capitalAltLabel ?coord ?iso2 ?iso3 WHERE {
  ?country wdt:P31 wd:Q3624078;
           wdt:P36 ?capital.
  OPTIONAL { ?country wdt:P297 ?iso2. }
  OPTIONAL { ?country wdt:P298 ?iso3. }
  ?capital wdt:P625 ?coord.
  SERVICE wikibase:label {
    bd:serviceParam wikibase:language "en,it,fr,es,de,pt,ru,zh,ar,ja,ko".
    ?country rdfs:label ?countryLabel.
    ?country skos:altLabel ?countryAltLabel.
    ?capital rdfs:label ?capitalLabel.
    ?capital skos:altLabel ?capitalAltLabel.
  }
}
"""


def clean_list(values):
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
    return cleaned


def parse_point(value: str) -> tuple[float, float] | None:
    if not value.startswith("Point(") or not value.endswith(")"):
        return None
    lon_text, lat_text = value.removeprefix("Point(").removesuffix(")").split()
    return float(lat_text), float(lon_text)


def binding_value(binding, key):
    value = binding.get(key)
    if not value:
        return ""
    return value.get("value", "")


def main() -> None:
    query = urllib.parse.urlencode({"query": WIKIDATA_QUERY, "format": "json"}).encode("utf-8")
    request = urllib.request.Request(
        WIKIDATA_ENDPOINT,
        data=query,
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "maptoposter-capitals-cache/1.0 (local development)",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    by_pair = {}
    for binding in payload["results"]["bindings"]:
        country_id = binding_value(binding, "country")
        capital_id = binding_value(binding, "capital")
        country_name = binding_value(binding, "countryLabel")
        capital_name = binding_value(binding, "capitalLabel")
        coordinates = parse_point(binding_value(binding, "coord"))
        if not country_id or not capital_id or not country_name or not capital_name or not coordinates:
            continue

        record = by_pair.setdefault(
            (country_id, capital_id),
            {
                "country": country_name,
                "country_official": country_name,
                "country_codes": [],
                "country_aliases": [],
                "capital": capital_name,
                "capital_aliases": [],
                "latitude": coordinates[0],
                "longitude": coordinates[1],
            },
        )

        record["country_aliases"] = clean_list(
            [
                *record["country_aliases"],
                country_name,
                binding_value(binding, "countryAltLabel"),
                binding_value(binding, "iso2"),
                binding_value(binding, "iso3"),
            ]
        )
        record["country_codes"] = clean_list(
            [*record["country_codes"], binding_value(binding, "iso2"), binding_value(binding, "iso3")]
        )
        record["capital_aliases"] = clean_list(
            [*record["capital_aliases"], capital_name, binding_value(binding, "capitalAltLabel")]
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": WIKIDATA_ENDPOINT,
        "capitals": sorted(by_pair.values(), key=lambda item: item["country"].casefold()),
    }

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['capitals'])} capital records to {OUTPUT}")


if __name__ == "__main__":
    main()
