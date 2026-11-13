// The agency list covers the Comptroller's register of Texas state agencies (data/agency_register.json).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {AGENCIES, AGENCY_NAME, SCOPE_AGENCY_ID} from '../src/taxonomy.js';

const register = JSON.parse(readFileSync(new URL('../data/agency_register.json', import.meta.url), 'utf8'));
const ids = AGENCIES.map(a => a.id);

test('every agency on the register is in the list', () => {
  assert.equal(register.agencies.length, 209);
  const missing = register.agencies.filter(a => !AGENCY_NAME[a.id]).map(a => `${a.number} ${a.name}`);
  assert.deepEqual(missing, []);
});

test('every listed agency is on the register or is a named unnumbered body', () => {
  const known = new Set([...register.agencies, ...register.unnumbered].map(a => a.id));
  assert.deepEqual(ids.filter(id => id !== SCOPE_AGENCY_ID && !known.has(id)), []);
  for (const a of register.unnumbered) assert.equal(AGENCY_NAME[a.id], a.name, a.id);
});

test('register numbers and ids are unique, and the list has no duplicate ids', () => {
  assert.equal(new Set(register.agencies.map(a => a.number)).size, register.agencies.length);
  assert.equal(new Set(register.agencies.map(a => a.id)).size, register.agencies.length);
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(ids.length, register.agencies.length + register.unnumbered.length + 1);  // + the scope tag
});

test('newly added agencies use the register name', () => {
  // Agencies the atlas had before the register keep their earlier, longer names (e.g. "Texas Department of Agriculture").
  const earlier = new Set(['ag', 'attorney-general', 'comptroller', 'dps', 'dshs', 'ers', 'glo', 'hhsc', 'oca', 'puc', 'rrc',
    'sos', 'tceq', 'tdcj', 'tdem', 'tdi', 'tdlr', 'tea', 'thc', 'thecb', 'tmb', 'tob', 'tpwd', 'trs', 'tsc', 'tss', 'twc', 'twdb',
    'txdmv', 'txdot', 'tdhca', 'tvc', 'tcole', 'texas-ethics', 'tac', 'tbpe', 'sbec', 'tbc', 'tsbvi', 'tsd', 'tsbp', 'tbn',
    'tsbpa', 'tba', 'tfc', 'veterans-land', 'ut-system', 'tamu-system', 'tx-juvenile', 'tpfa', 'tswcb']);
  for (const a of register.agencies) if (!earlier.has(a.id)) assert.equal(AGENCY_NAME[a.id], a.atlas_name || a.name, a.id);
});

test('ids are lower-case slugs', () => {
  for (const id of ids) assert.match(id, /^[a-z0-9]+(-[a-z0-9]+)*$/);
});
