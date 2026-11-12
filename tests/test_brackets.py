import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_feeds as b  # noqa: E402

TABLE = {
    "format": b.POPULATION_FORMAT, "source": "test",
    "counties": {"48201": ["Harris County", 4731145], "48113": ["Dallas County", 2613539],
                 "48439": ["Tarrant County", 2110640], "48001": ["Anderson County", 57922],
                 "48009": ["Archer County", 8560]},
    "places": {"4835000": ["Houston city", 2304580, "48201"], "4861592": ["Reno city", 3454, "48277"],
               "4861604": ["Reno city", 2878, "48367"]},
}


@pytest.mark.parametrize("text,bounds", [
    ("more than four million", (4_000_001, None)),
    ("4 million or more", (4_000_000, None)),
    ("in excess of 1.1 million", (1_100_001, None)),
    ("less than 100,000", (None, 99_999)),
    ("200,000 or less", (None, 200_000)),
    ("50,000 or more but less than 250,000", (50_000, 249_999)),
    ("more than 11,450 and less than 11,550", (11_451, 11_549)),
    ("at least 3,200", (3_200, None)),
    ("not more than 15,000", (None, 15_000)),
])
def test_bounds(text, bounds):
    assert b.bracket_bounds(text) == bounds


def test_bare_number_is_not_read_as_exact():
    assert b.bracket_bounds("3,000") is None
    assert b.bracket_bounds("more than 500,000 and less than 100,000") is None


def section(clause, *body):
    return "\n\n".join(["### SECTION 1.", clause, *body])


def test_operator_after_in_excess_of_is_kept():
    clauses, unparsed = b.bill_brackets(section("This Act applies only to a municipality having a population in excess "
                                                "of 1.1 million."))
    assert [(c["status"], c["bounds"]) for c in clauses] == [("new", (1_100_001, None))]
    assert unparsed == 0


def test_bare_number_counts_as_unparsed():
    clauses, unparsed = b.bill_brackets(section("This Act applies only to a county with a population of 3,000."))
    assert clauses == [] and unparsed == 1


def test_unmarked_text_is_new_outside_amended_code_and_existing_inside():
    uncodified = section("This Act applies only to a county with a population of more than four million.")
    amended = section("Section 81.001, Local Government Code, is amended to read as follows:",
                      "Sec. 81.001. X. (a) This applies to a county with a population of more than four million.",
                      "<ins>(b) And to a county with a population of 2.5 million or more.</ins>")
    assert [c["status"] for c in b.bill_brackets(uncodified)[0]] == ["new"]
    assert [(c["status"], c["bounds"][0]) for c in b.bill_brackets(amended)[0]] == [("existing", 4_000_001), ("new", 2_500_000)]


def test_threshold_change_is_paired_with_old_wording():
    text = section("Section 1.001, Local Government Code, is amended to read as follows:",
                   r"(b) This section applies only to a county with a population of <ins>100,000</ins> \[<del>3.3 million</del>\] or more.")
    [c] = b.bill_brackets(text)[0]
    assert c["status"] == "changed" and c["bounds"] == (100_000, None)
    assert c["was"]["bounds"] == (3_300_000, None)


def test_struck_bracket_is_removed():
    text = section("Section 1.001, Local Government Code, is amended to read as follows:",
                   r"(b) This applies \[<del>only to a county with a population of more than 600,000</del>\] to every county.")
    assert [c["status"] for c in b.bill_brackets(text)[0]] == ["removed"]


def test_older_census_is_marked_and_not_resolved(tmp_path):
    text = section("This Act applies only to a county with a population of more than 600,000 according to the 2010 "
                   "federal decennial census.")
    [c] = b.bill_brackets(text)[0]
    assert c["census"] == 2010
    row = build(tmp_path, text)["bills"]["HB1"]["c"][0]
    assert row["census"] == 2010 and "n" not in row and "p" not in row


def test_list_items_take_the_lead_in_and_joint_lists_are_conditions():
    alternatives = section("This Act applies only to a school district located in a county:",
                           "(1) with a population of 2.1 million or more; or", "(2) that borders Mexico.")
    joint = section("This section applies only to a county that:", "(1) has a population of less than 100,000; and",
                    "(2) borders Mexico.")
    [alt] = b.bill_brackets(alternatives)[0]
    [cond] = b.bill_brackets(joint)[0]
    assert (alt["kind"], alt["bounds"], alt["cond"]) == ("county", (2_100_000, None), False)
    assert (cond["kind"], cond["bounds"], cond["cond"]) == ("county", (None, 99_999), True)
    last_item = section("This section applies only to a municipality that:", "(1) borders Mexico; and",
                        "(2) has a population of 15,000 or more.")
    [last] = b.bill_brackets(last_item)[0]
    assert (last["kind"], last["cond"]) == ("city", True)


def test_condition_after_bracket_is_flagged():
    text = section("This Act applies only to a county with a population of 2.5 million or more that is adjacent to a "
                   "county with a population of more than four million.")
    flags = [c["cond"] for c in b.bill_brackets(text)[0]]
    assert flags == [True, False]


def build(tmp_path, markdown, bill="HB1", table=TABLE):
    text_dir = tmp_path / "text"
    (text_dir / bill).mkdir(parents=True, exist_ok=True)
    (text_dir / bill / "index.json").write_text(json.dumps({"bill_id": bill, "versions": [{"code": "I", "name": "Introduced"}]}))
    (text_dir / bill / "I.md").write_text(markdown, "utf-8")
    return b.build_brackets({"bills": [{"id": bill}]}, text_dir, table)


def test_resolution_lists_places_and_changes(tmp_path):
    text = section("Section 1.001, Local Government Code, is amended to read as follows:",
                   r"(b) This applies only to a county with a population of <ins>2.5 million</ins> \[<del>four million</del>\] or more.")
    index = build(tmp_path, text)
    [row] = index["bills"]["HB1"]["c"]
    assert row["p"] == ["48201", "48113"] and row["n"] == 2
    assert row["was"]["n"] == 1 and row["was"]["added_p"] == ["48113"] and row["was"]["dropped"] == 0
    assert index["places"]["48113"] == ["Dallas County", 2613539]


def test_places_carry_their_county_and_big_sets_are_only_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "BRACKET_LIST_MAX", 1)
    index = build(tmp_path, section("This Act applies only to a municipality with a population of less than 5,000."))
    [row] = index["bills"]["HB1"]["c"]
    assert row["n"] == 2 and row["p"] is None
    index = build(tmp_path, section("This Act applies only to a municipality with a population of more than 3,000 and "
                                    "less than 3,500."))
    assert index["places"]["4861592"] == ["Reno city", 3454, ""]  # county 48277 is not in the test table


def test_resolutions_are_skipped(tmp_path):
    index = build(tmp_path, "WHEREAS, the county has a population of more than one million;", bill="HR13")
    assert index["bills"] == {}


@pytest.mark.parametrize("content", [None, "", "{not json", json.dumps({"format": "other"}),
                                     json.dumps({**TABLE, "counties": {"48201": ["Harris County", "many"]}})])
def test_missing_or_bad_census_table_skips_without_failing(tmp_path, content):
    census = tmp_path / "census.json"
    if content is not None:
        census.write_text(content)
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    status = b.write_brackets({"bills": []}, text_dir, census, tmp_path / "brackets")
    assert status.startswith("skipped") and not (tmp_path / "brackets").exists()


def test_main_still_succeeds_without_census_table(tmp_path, monkeypatch, capsys):
    snapshot = tmp_path / "bills.json"
    snapshot.write_text(json.dumps({"bills": []}))
    (tmp_path / "text").mkdir()
    monkeypatch.setattr(sys, "argv", ["build_feeds.py", "--snapshot", str(snapshot), "--out", str(tmp_path / "feeds"),
                                      "--census", str(tmp_path / "missing.json")])
    assert b.main() == 0
    assert "Population brackets: skipped" in capsys.readouterr().out


def test_repository_census_table_is_valid():
    table = b.load_population(Path(__file__).resolve().parents[1] / "data" / "census" / "tx_population_2020.json")
    assert table is not None and len(table["counties"]) == 254
    assert sum(v[1] for v in table["counties"].values()) == 29_145_505
    assert table["counties"]["48201"] == ["Harris County", 4731145]


def test_between_is_inclusive_and_its_threshold_change_pairs():
    assert b.bracket_bounds("between 10,000 and 200,000") == (10_000, 200_000)
    assert b.bracket_bounds("between 200,000 and 10,000") is None
    text = section("Section 1.001, Local Government Code, is amended to read as follows:",
                   r"(2) for a county with a population between 10,000 and <ins>200,000</ins> \[<del>68,750</del>\], $350,000.")
    [c] = b.bill_brackets(text)[0]
    assert c["status"] == "changed" and c["bounds"] == (10_000, 200_000) and c["was"]["bounds"] == (10_000, 68_750)


def test_county_or_municipality_is_both_and_plural_populations_read():
    text = section("This Act applies to an event in a county or municipality with a population of less than 500,000 "
                   "and to counties with populations of more than 3,000.")
    assert sorted(((c["kind"], c["bounds"]) for c in b.bill_brackets(text)[0]), key=repr) == sorted([
        ("city", (None, 499_999)), ("county", (None, 499_999)), ("county", (3_001, None))], key=repr)


@pytest.mark.parametrize("wording,rel", [
    ("a county that is adjacent to a county with a population of 4 million or more", "near"),
    ("a county that borders a county with a population of 4 million or more", "near"),
    ("a county on the international border that contains a municipality with a population of 500,000 or more", "inside"),
    ("a county that includes a municipality with a population of more than 500,000", "inside"),
    ("a municipality that is the county seat of a county with a population of more than 10,000", "seat"),
    ("an authority in which the principal municipality has a population of less than 1.9 million", "principal"),
    ("an entity located in a county with a population of 800,000 or more", None),
    ("a county with a population of 800,000 or more", None),
])
def test_tests_on_related_places_are_marked(wording, rel):
    [c] = b.bill_brackets(section(f"This Act applies only to {wording}."))[0]
    assert c["rel"] == rel


def test_related_flag_reaches_the_index(tmp_path):
    index = build(tmp_path, section("This Act applies only to a county with a population of 800,000 or more that is "
                                    "adjacent to a county with a population of 4 million or more."))
    rows = index["bills"]["HB1"]["c"]
    assert [r.get("rel") for r in rows] == [None, "near"]


def test_lead_in_naming_no_place_keeps_the_one_before_and_relabelled_items_pair():
    text = section("Section 1.001, Local Government Code, is amended to read as follows:",
                   r"(a) This chapter applies only to a municipality\[<del>:</del>",
                   r"\[<del>(1)</del>\] that:",
                   r"<ins>(1)</ins> \[<del>(A)</del>\] has a population of <ins>25,000</ins> \[<del>10,000</del>\] or more; <ins>and</ins>",
                   "<ins>(2)</ins> is subject to restrictive covenants.")
    [c] = b.bill_brackets(text)[0]
    assert (c["kind"], c["status"], c["bounds"], c["was"]["bounds"], c["cond"]) == ("city", "changed", (25_000, None), (10_000, None), True)


def test_every_unread_population_phrase_is_counted_but_percentages_are_not():
    text = section("This Act applies only to a municipality located in two counties, one of which has a population of "
                   "less than 110,000, and to a county with a population of either more than 600,000 or less than 50,000.",
                   "This Act applies to a county with a population of 3,000 or more.",
                   "A district whose population is at least 70 percent of the county's is not covered.")
    clauses, unparsed = b.bill_brackets(text)
    assert [c["bounds"] for c in clauses] == [(3_000, None)]
    assert unparsed == 2  # "one of which has a population of less than 110,000" and the "either ... or" test


def test_each_clause_keeps_its_own_section():
    text = ("### SECTION 1.\n\nThis Act applies only to a county with a population of more than four million.\n\n"
            "### SECTION 2.\n\nThis Act applies only to a municipality with a population of 50,000 or more.")
    assert [c["section"] for c in b.bill_brackets(text)[0]] == ["SECTION 1", "SECTION 2"]
