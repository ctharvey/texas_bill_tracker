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



class LunaNamesWithoutTheListTests(unittest.TestCase):
    """Luna names bodies without seeing the agency list; code decides which listed agency a name means."""

    def doc(self, text="The Texas Department of Transportation shall build markers."):
        return detailed.document_from_pages("HB1", "90R", "introduced", [text])

    def test_the_request_carries_no_agency_list(self):
        import classify_bill
        request = classify_bill.build_request(self.doc(), detailed.load_registry())
        prompt = request["input"][0]["content"][0]["text"]
        self.assertIn('"agencies":[]', prompt)
        for name in ("Texas Cyber Command", "Health and Human Services Commission", "Texas Optometry Board"):
            self.assertNotIn(name, prompt)
        self.assertIn("all-state-agencies", prompt)  # the scope marker is still described
        self.assertIn("Always set registry_id to null", prompt)

    def test_the_request_does_not_change_when_the_list_grows(self):
        import classify_bill
        registry = detailed.load_registry()
        grown = registry + [{"id": "new-body", "name": "Texas New Body"}]
        self.assertEqual(classify_bill.build_request(self.doc(), registry), classify_bill.build_request(self.doc(), grown))

    def test_only_generic_names_are_identity_questions(self):
        def questions(name):
            result = {"summary": {"text": "A bill.", "evidence": []}, "uncertainties": [], "major_effects": [],
                      "affected_groups": [], "agencies": [{"registry_id": None, "name": name, "explanation": "x",
                                                           "evidence": [{"span_id": "P001S001", "quote": "x"}]}]}
            return pipeline.questions_for(result, {"spans": {}})
        self.assertEqual(len(questions("the department")), 1)
        self.assertEqual(len(questions("Board")), 1)
        self.assertEqual(questions("Texas Department of Transportation"), [])     # on the list
        self.assertEqual(questions("state auditor"), [])                          # an alias
        self.assertEqual(questions("Texas Department of Artificial Intelligence"), [])  # named, not listed

    def test_generic_names(self):
        for name in ("the department", "Board", "state agency", "each appropriate state agency", "the commissioner",
                     "law enforcement agencies", "the executive commissioner"):
            self.assertTrue(pipeline.is_generic_agency_name(name), name)
        for name in ("Texas Department of Transportation", "state auditor", "Office of the State Long-Term Care Ombudsman",
                     "Austin Independent School District", "Commission on Jail Standards", ""):
            self.assertFalse(pipeline.is_generic_agency_name(name), name)

    def test_the_validator_flags_only_unplaceable_generic_names(self):
        import classify_bill
        from test_classify_bill import result
        registry = detailed.load_registry()
        doc = detailed.document_from_pages("HB1", "90R", "introduced", ["The department shall build markers."])
        schema = classify_bill.build_request(doc, registry)["text"]["format"]["schema"]

        def reasons(name):
            value = result()
            value["agencies"] = [{"registry_id": None, "name": name, "impact": "direct", "explanation": "Builds.",
                                  "evidence": [{"span_id": "P001S001", "quote": "The department shall build markers."}]}]
            return classify_bill.validate_result(value, doc, registry, schema, "f" * 64)["review_reasons"]
        self.assertIn("Unresolved agency identity: the department", reasons("the department"))
        self.assertNotIn("Unresolved agency identity: Texas Department of Transportation",
                         reasons("Texas Department of Transportation"))
        self.assertFalse([r for r in reasons("Texas Department of Artificial Intelligence") if "identity" in r])

    def test_published_fiscal_agencies_get_a_listed_id(self):
        import review_stages
        self.assertEqual(review_stages._listed_id("Texas Department of Transportation"), "txdot")
        self.assertEqual(review_stages._listed_id("Department of Family and Protective Services"), "dfps")
        self.assertIsNone(review_stages._listed_id("the department"))

if __name__ == "__main__":
    unittest.main()
