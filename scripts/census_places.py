#!/usr/bin/env python3
"""Writes data/census/tx_population_2020.json from the 2020 Census P.L. 94-171 geographic header for Texas.

Download https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/Texas/tx2020.pl.zip
(no key needed), unzip it, and pass txgeo2020.pl. The population bracket build in build_feeds.py reads the output.
Counties are summary level 050; municipalities are incorporated places (level 160, class C*), each with the county
holding most of its people (level 155) so places sharing a name can be told apart.
"""
import argparse
import json
from pathlib import Path

# Field positions in the pipe-delimited 2020 geographic header (2020 P.L. 94-171 technical documentation).
SUMLEV, GEOCOMP, STATE, COUNTY, PLACE, PLACECC, NAME, FUNCSTAT, POP100 = 2, 4, 12, 14, 29, 30, 87, 88, 90
TEXAS_COUNTIES, TEXAS_TOTAL = 254, 29_145_505
FORMAT = "texas-population-2020-v1"


def read_header(path: Path) -> dict:
    counties, places, parts = {}, {}, {}
    with path.open(encoding="latin-1") as f:
        for line in f:
            r = line.rstrip("\n").split("|")
            if r[GEOCOMP] != "00" or r[STATE] != "48":
                continue
            if r[SUMLEV] == "050":
                counties[r[STATE] + r[COUNTY]] = [r[NAME], int(r[POP100])]
            elif r[SUMLEV] == "160" and r[PLACECC].startswith("C") and r[FUNCSTAT] == "A":
                places[r[STATE] + r[PLACE]] = [r[NAME], int(r[POP100])]
            elif r[SUMLEV] == "155":
                parts.setdefault(r[STATE] + r[PLACE], []).append((int(r[POP100]), r[STATE] + r[COUNTY]))
    if len(counties) != TEXAS_COUNTIES or sum(p for _, p in counties.values()) != TEXAS_TOTAL:
        raise SystemExit(f"Unexpected county extract: {len(counties)} counties, {sum(p for _, p in counties.values())} people")
    for geoid, place in places.items():
        if geoid not in parts:
            raise SystemExit(f"No county part for place {geoid} {place[0]}")
        place.append(max(parts[geoid])[1])
    return {"format": FORMAT, "source": "2020 Census Redistricting Data (P.L. 94-171), total population (POP100)",
            "counties": dict(sorted(counties.items())), "places": dict(sorted(places.items()))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geo", type=Path, help="txgeo2020.pl from tx2020.pl.zip")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "census" / "tx_population_2020.json")
    args = parser.parse_args()
    table = read_header(args.geo)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    print(f"{len(table['counties'])} counties, {len(table['places'])} places -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
