"""Build the "Near you" geography files in data/geo/ from official sources. Desktop-only; the server never runs it.

Inputs (download into one folder; see README "Near you data"):
  planh2316.zip, plans2168.zip           Texas Legislative Council district shapefiles (2023-2026 plans)
  h_r150.xls, s_r150.xls                 TLC report 150, Districts by County (House, Senate)
  h_r125.xls, s_r125.xls                 TLC report 125, Cities and CDPs by District (House, Senate)
  cb_2024_us_county_500k.zip             Census cartographic county boundaries (Texas is filtered out)

Needs xlrd 2.0.1 (reads the .xls reports) and mapshaper 0.7.98 (simplifies the shapes), both build-time only:
    python scripts/build_districts.py --inputs <folder> [--mapshaper "npx --yes mapshaper@0.7.98"]

Writes data/geo/districts.json (the tables) and house.json, senate.json, counties.json (GeoJSON, WGS84). District
outlines are simplified to within SIMPLIFY_M metres, counties to within COUNTY_SIMPLIFY_M; the page warns near a line.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "geo"
FORMAT = "texas-bill-districts-v1"
PLANS = {"house": "PLANH2316", "senate": "PLANS2168"}
SIMPLIFY_M = 100
COUNTY_SIMPLIFY_M = 250
TLC_LCC = ("+proj=lcc +x_0=1000000 +y_0=1000000 +lon_0=-100 +lat_1=27.41666666666667 +lat_2=34.91666666666666 "
           "+lat_0=31.16666666666667 +datum=NAD83")
SOURCES = {
    "districts": "Texas Legislative Council, data.capitol.texas.gov: PLANH2316 and PLANS2168 (2023-2026), "
                 "shapefiles and reports 125 and 150",
    "counties": "US Census Bureau cartographic boundary file cb_2024_us_county_500k (Texas)",
}
_SHARE = re.compile(r"^(?P<name>.+?)\s*\((?P<pct>[\d.]+)\s*%\)$")
_DISTRICT = re.compile(r"^DISTRICT\s+(\d+)$")


def _rows(path: Path) -> list[list]:
    import xlrd
    with open(path, "rb") as handle:
        data = handle.read()
    sheet = xlrd.open_workbook(file_contents=data, logfile=open(os.devnull, "w")).sheet_by_index(0)
    return [sheet.row_values(r) for r in range(sheet.nrows)]


def _number(value) -> str | None:
    return str(int(value)) if isinstance(value, float) and value == int(value) and value > 0 else None


def parse_r150(rows: list[list]) -> dict[str, dict[str, float]]:
    """county -> {district: share of the county's population}. An unsplit county has one district at 1.0."""
    out: dict[str, dict[str, float]] = {}
    county = None
    for row in rows:
        name = str(row[2]).strip() if len(row) > 2 else ""
        if name and name not in ("County",) and not name.startswith("Red-"):
            county = name
            out.setdefault(county, {})
            continue
        district = _number(row[5]) if len(row) > 5 else None
        if county and district:
            pct = str(row[6]).strip() if len(row) > 6 else ""
            out[county][district] = round(float(pct.rstrip(" %")) / 100, 4) if pct else 1.0
    return {c: d for c, d in out.items() if d}


def parse_r125(rows: list[list]) -> dict[str, dict]:
    """district -> {counties: {county: share}, places: [{name, county, share, cdp}]}. County lines carry no
    population columns; place lines do. "Rest of County" is not a place."""
    out: dict[str, dict] = {}
    district = county = None
    for row in rows:
        label = str(row[2]).strip() if len(row) > 2 else ""
        if not label:
            continue
        found = _DISTRICT.match(label)
        if found:
            district, county = found[1], None
            out[district] = {"counties": {}, "places": []}
            continue
        share = _SHARE.match(label)
        if district is None or label == "Rest of County":
            continue
        has_totals = len(row) > 4 and str(row[4]).strip() == "Total:"
        if share and not has_totals:
            county = share["name"]
            out[district]["counties"][county] = round(float(share["pct"]) / 100, 4)
        elif share and county:
            name, cdp = share["name"].rstrip(" *"), False  # "*" marks a place that spans counties
            if name.endswith("(CDP)"):
                name, cdp = name[:-5].strip(), True
            out[district]["places"].append({"name": name, "county": county,
                                            "share": round(float(share["pct"]) / 100, 4), "cdp": cdp})
    return out


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def tables(h150, s150, h125, s125) -> dict:
    by_county = {"house": parse_r150(h150), "senate": parse_r150(s150)}
    by_district = {"house": parse_r125(h125), "senate": parse_r125(s125)}
    counties: dict[str, dict] = {}
    for chamber, table in by_county.items():
        for county, districts in table.items():
            counties.setdefault(county, {"house": {}, "senate": {}})[chamber] = districts
    # Report 125 spells a few counties differently ("De Witt"); report 150's spelling (the Census one) wins.
    canonical = {_key(c): c for c in counties}
    for table in by_district.values():
        for entry in table.values():
            entry["counties"] = {canonical.get(_key(c), c): s for c, s in entry["counties"].items()}
            for place in entry["places"]:
                place["county"] = canonical.get(_key(place["county"]), place["county"])
    places: dict[str, dict] = {}
    for chamber, table in by_district.items():
        for district, entry in table.items():
            for place in entry["places"]:
                item = places.setdefault(place["name"], {"counties": [], "cdp": place["cdp"], "house": [],
                                                         "senate": []})
                if place["county"] not in item["counties"]:
                    item["counties"].append(place["county"])
                if district not in item[chamber]:
                    item[chamber].append(district)
    for item in places.values():
        item["counties"].sort()
        for key in ("house", "senate"):
            item[key].sort(key=int)
    districts = {chamber: {d: {"counties": e["counties"], "places": [p["name"] for p in e["places"]]}
                           for d, e in sorted(table.items(), key=lambda kv: int(kv[0]))}
                 for chamber, table in by_district.items()}
    return {"counties": dict(sorted(counties.items())), "places": dict(sorted(places.items())),
            "districts": districts}


def check(data: dict, shapes: dict[str, list[str]]) -> list[str]:
    """Problems that must stop the build: the tables and the shapes disagree, or a county is missing."""
    problems = []
    expected = {"house": 150, "senate": 31}
    for chamber, count in expected.items():
        want = {str(n) for n in range(1, count + 1)}
        if set(shapes[chamber]) != want:
            problems.append(f"{chamber} shapes: districts {sorted(want ^ set(shapes[chamber]), key=int)} differ")
        if set(data["districts"][chamber]) != want:
            problems.append(f"{chamber} report 125: districts {sorted(want ^ set(data['districts'][chamber]), key=int)}")
        in_counties = {d for c in data["counties"].values() for d in c[chamber]}
        if in_counties != want:
            problems.append(f"{chamber} report 150: districts {sorted(want ^ in_counties, key=int)}")
    if len(data["counties"]) != 254:
        problems.append(f"{len(data['counties'])} counties in report 150, expected 254")
    if set(shapes["counties"]) != set(data["counties"]):
        problems.append(f"county names differ: {sorted(set(shapes['counties']) ^ set(data['counties']))[:10]}")
    for chamber in ("house", "senate"):
        for district, entry in data["districts"][chamber].items():
            for county in entry["counties"]:
                if district not in data["counties"].get(county, {}).get(chamber, {}):
                    problems.append(f"{chamber} {district}: {county} in report 125 but not in report 150")
    return problems


def simplify(mapshaper: list[str], source: Path, out: Path, *, field: str, rename: str, interval: int,
             texas_only: bool = False) -> None:
    command = [*mapshaper, "-i", str(source)]
    if texas_only:
        command += ["-filter", 'STATEFP=="48"', "-filter-fields", field]
    command += ["-rename-fields", f"{rename}={field}"]
    if texas_only:
        command += ["-proj", TLC_LCC]  # simplify in metres, like the district files' own projection
    command += ["-simplify", f"interval={interval}", "keep-shapes", "-proj", "wgs84",
                "-o", str(out), "format=geojson", "precision=0.0001", "force"]
    subprocess.run(command, check=True, capture_output=True, shell=False)


def names(path: Path, key: str) -> list[str]:
    return [str(f["properties"][key]) for f in json.loads(path.read_text("utf-8"))["features"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--mapshaper", default="npx --yes mapshaper@0.7.98")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    tool = shlex.split(args.mapshaper, posix=True)
    if tool and tool[0] == "npx":
        import shutil
        tool[0] = shutil.which("npx") or "npx"  # Windows needs npx.cmd's full path without a shell
    args.out.mkdir(parents=True, exist_ok=True)
    i = args.inputs
    simplify(tool, i / "planh2316.zip", args.out / "house.json", field="District", rename="district",
             interval=SIMPLIFY_M)
    simplify(tool, i / "plans2168.zip", args.out / "senate.json", field="District", rename="district",
             interval=SIMPLIFY_M)
    simplify(tool, i / "cb_2024_us_county_500k.zip", args.out / "counties.json", field="NAME", rename="county",
             interval=COUNTY_SIMPLIFY_M, texas_only=True)
    data = tables(_rows(i / "h_r150.xls"), _rows(i / "s_r150.xls"), _rows(i / "h_r125.xls"), _rows(i / "s_r125.xls"))
    shapes = {"house": names(args.out / "house.json", "district"),
              "senate": names(args.out / "senate.json", "district"),
              "counties": names(args.out / "counties.json", "county")}
    problems = check(data, shapes)
    if problems:
        for problem in problems:
            print("PROBLEM:", problem)
        return 1
    payload = {"format": FORMAT, "plans": PLANS, "simplified_m": {"districts": SIMPLIFY_M,
                                                                   "counties": COUNTY_SIMPLIFY_M},
               "sources": SOURCES, "built_on": dt.date.today().isoformat(), **data}
    (args.out / "districts.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                                             "utf-8")
    print(f"Wrote {args.out}: {len(data['counties'])} counties, {len(data['places'])} places")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
