"""Roster matching must be exact on surname and agree on given name; parsing keeps every service stint."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sync_members as sm

ROW = '''<tr><th scope="row"><a href="memberDisplay.cfm?memberID=5670&x=1"><img alt="Headshot of Carol Alvarado"> Carol Alvarado</a></td>
<td class="results"></td><td>6</td><td>S<br> H<br></td><td>2018 - 2029<br> 2009 - 2018<br></td>
<td>85th - 90th <br> 81st - 85th <br></td><td>D<br> D<br></td><td>Houston, Harris</td><td>Harris</td></tr>'''


class MatchTests(unittest.TestCase):
    def test_name_variants_that_are_the_same_person(self):
        self.assertTrue(sm.same_person('John Bucy III', 'Bucy', 'John H. Bucy III'))
        self.assertTrue(sm.same_person('Mary E. González', 'González, Mary', 'Mary González'))
        self.assertTrue(sm.same_person('Thresa "Terry" Meza', 'Meza', 'Terry Meza'))
        self.assertTrue(sm.same_person('Vincent Perez', 'Perez, Vincent', 'Vince Perez'))

    def test_different_people_sharing_a_surname_do_not_match(self):
        self.assertFalse(sm.same_person('Vincent Perez', 'Perez, Vincent', 'Mary Ann Perez'))
        self.assertFalse(sm.same_person('Juan Hinojosa', 'Hinojosa, Juan "Chuy"', 'Adam Hinojosa'))
        self.assertFalse(sm.same_person('Juan Hinojosa', 'Hinojosa, Juan "Chuy"', 'Gina Hinojosa'))
        self.assertFalse(sm.same_person('Molly Cook', 'Cook, Molly', 'David Cook'))
        self.assertFalse(sm.same_person('Al Smith', 'Smith', 'Alvin Smithers'))

    def test_compound_surnames_must_match_whole(self):
        self.assertTrue(sm.same_person('Trey Martinez Fischer', 'Martinez Fischer', 'Trey Martinez Fischer'))
        self.assertFalse(sm.same_person('Ana Fischer', 'Fischer', 'Trey Martinez Fischer'))


class ElectTests(unittest.TestCase):
    def test_ballot_names_agree_with_tlo_names(self):
        import json
        data = sm.load_elect(ROOT / 'data' / 'members_elect_2026.json')
        self.assertEqual(len(data['members']), 41)
        names = {'Oziel Ochoa, Jr.': 'Ochoa', 'Beth McLaughlin': 'McLaughlin', 'Odus Evbagharu': 'Evbagharu',
                 'Dennis Geesaman': 'Geesaman', 'Tyler Smith': 'Smith'}
        for full, display in names.items():
            self.assertTrue(sm.same_person(full, display, data['members']['house|' + display]['ballot_name']), display)
        self.assertFalse(sm.same_person('Lauren Smith', 'Smith', data['members']['house|Smith']['ballot_name']))
        self.assertTrue(all(v['party'] in ('Democratic', 'Republican') for v in data['members'].values()))


class ParseTests(unittest.TestCase):
    def test_lrl_row_keeps_each_stint_and_tenure(self):
        [row] = sm.lrl_rows('<tr><th>header</th></tr>' + ROW)
        self.assertEqual(row['lrl_id'], '5670')
        self.assertEqual(row['name'], 'Carol Alvarado')
        self.assertEqual([s['chamber'] for s in row['stints']], ['senate', 'house'])
        self.assertEqual(row['stints'][0]['party'], 'D')
        self.assertEqual(sm.service_years(row['stints']), 18)  # Counted only up to the 90th's 2027 start.

    def test_quoted_nickname_keeps_the_full_name(self):
        row = ROW.replace('alt="Headshot of Carol Alvarado"> Carol Alvarado',
                          'alt="Headshot of Juan "Chuy" Hinojosa">&nbsp;&nbsp; Juan "Chuy" Hinojosa')
        [parsed] = sm.lrl_rows('<tr><th>header</th></tr>' + row)
        self.assertEqual(parsed['name'], 'Juan "Chuy" Hinojosa')
        self.assertTrue(sm.same_person('Juan Hinojosa', 'Hinojosa, Juan "Chuy"', parsed['name']))

    def test_unparseable_years_give_unknown_tenure(self):
        self.assertIsNone(sm.service_years([{'years': 'unknown'}]))


if __name__ == '__main__':
    unittest.main()
