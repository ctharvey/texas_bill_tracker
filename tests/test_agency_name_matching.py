"""Publish-time agency name matching: Luna agency names that are listed agencies get their registry id."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import extract_bill as detailed  # noqa: E402
import review_pipeline as pipeline  # noqa: E402

NAMES = {a["id"]: a["name"] for a in detailed.load_registry() if a["id"] != "all-state-agencies"}


def agency(name, registry_id=None, impact="direct"):
    return {"name": name, "registry_id": registry_id, "impact": impact, "explanation": "x", "evidence": []}


def named(name, registry_id=None, names=NAMES):
    return pipeline.agency_id_for(agency(name, registry_id), {}, names)


class NameKeyTests(unittest.TestCase):
    def test_case_accents_punctuation_and_texas_are_ignored(self):
        key = pipeline.agency_name_key
        self.assertEqual(key("Railroad Commission of Texas"), "railroad commission")
        self.assertEqual(key("the Texas Railroad Commission"), "railroad commission")
        self.assertEqual(key("TEXAS A&M UNIVERSITY"), key("Texas A and M University"))
        self.assertEqual(key("Comisión"), "comision")
        self.assertEqual(key("State Auditor’s Office"), key("state auditor's office"))
        self.assertEqual(key(""), "")

    def test_listed_names_do_not_collide(self):
        keys = [pipeline.agency_name_key(n) for n in NAMES.values()]
        self.assertEqual(len(keys), len(set(keys)))


class UnmappedNameTests(unittest.TestCase):
    def test_a_listed_name_gets_its_id(self):
        self.assertEqual(named("Department of Family and Protective Services"), "dfps")
        self.assertEqual(named("Texas Department of Family and Protective Services"), "dfps")
        self.assertEqual(named("Commission on Jail Standards"), "jail-standards")
        self.assertEqual(named("Texas Cyber Command"), "cyber-command")
        self.assertEqual(named("The University of Texas Health Science Center at Houston"), "uthealth-houston")
        self.assertEqual(named("Board of Pardons and Paroles"), "bpp")

    def test_an_alias_gets_its_agency(self):
        self.assertEqual(named("Governor"), "governor")
        self.assertEqual(named("office of the governor"), "governor")
        self.assertEqual(named("comptroller"), "comptroller")
        self.assertEqual(named("state auditor"), "sao")
        self.assertEqual(named("Texas Transportation Commission"), "txdot")
        self.assertEqual(named("commissioner of education"), "tea")
        self.assertEqual(named("coordinating board"), "thecb")

    def test_generic_and_unknown_names_stay_unmapped(self):
        for name in ("the department", "commission", "state agency", "court", "trial court", "Texas Redistricting Commission",
                     "Bureau of Economic Geology of The University of Texas at Austin", "executive commissioner", ""):
            self.assertIsNone(named(name), name)

    def test_an_alias_for_an_agency_not_in_the_registry_is_ignored(self):
        self.assertIsNone(named("Governor", names={"tea": "Texas Education Agency"}))
        self.assertEqual(named("Texas Education Agency", names={"tea": "Texas Education Agency"}), "tea")

    def test_a_name_two_agencies_share_maps_to_neither(self):
        names = {"a": "Texas Example Board", "b": "Example Board of Texas"}
        self.assertIsNone(named("Example Board", names=names))

    def test_no_registry_means_no_mapping(self):
        self.assertIsNone(pipeline.agency_id_for(agency("Texas Education Agency"), {}, None))


class MappedNameTests(unittest.TestCase):
    def test_a_name_that_is_another_listed_agency_replaces_lunas_id(self):
        self.assertEqual(named("Texas Department of Family and Protective Services", "dps"), "dfps")

    def test_lunas_id_stands_when_the_name_agrees_or_is_not_an_exact_listing(self):
        self.assertIsNone(named("Texas Department of Public Safety", "dps"))
        self.assertIsNone(named("Texas Transportation Commission", "txdot"))
        self.assertIsNone(named("Office of Court Administration of the Texas Judicial System", "oca"))
        self.assertIsNone(named("the department", "txdot"))


class PublicAgenciesTests(unittest.TestCase):
    def publish(self, *agencies):
        return [(a["id"], a["name"]) for a in pipeline.public_agencies(list(agencies), {}, NAMES)]

    def test_matched_labels_take_the_listed_name(self):
        self.assertEqual(self.publish(agency("state auditor")), [("sao", NAMES["sao"])])
        self.assertEqual(self.publish(agency("Department of Information Resources"), agency("the department")),
                         [("dir", NAMES["dir"]), (None, "the department")])

    def test_a_match_for_an_agency_already_listed_is_dropped(self):
        self.assertEqual(self.publish(agency("Texas Department of Transportation", "txdot"),
                                      agency("Texas Transportation Commission")),
                         [("txdot", "Texas Department of Transportation")])

    def test_a_corrected_id_is_published_with_the_listed_name(self):
        self.assertEqual(self.publish(agency("Texas Department of Family and Protective Services", "dps")),
                         [("dfps", NAMES["dfps"])])


if __name__ == "__main__":
    unittest.main()
