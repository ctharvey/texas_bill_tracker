import test from 'node:test';
import assert from 'node:assert/strict';
import {loadShardedMap} from '../src/core/net.js';

const FORMAT = 'texas-bill-luna-tags-v1';
const shard = (n, bills) => ({format: 'texas-bill-luna-shard-v1', of: FORMAT, shard: n, bills});

function server(files) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({url, cache: options?.cache});
    const path = url.split('?')[0];
    if (!(path in files)) return {ok: false, status: 404, json: async () => null};
    return {ok: true, status: 200, json: async () => structuredClone(files[path])};
  };
  return {fetchImpl, calls};
}

const index = {format: 'texas-bill-luna-shards-v2', of: FORMAT, model: 'm', generated_at: '2026-11-15T00:00:00Z',
  agencies: {A: 'Agency'}, shards: ['aaaaaaaaaaaaaaaaaaaa', 'bbbbbbbbbbbbbbbbbbbb']};

test('shards merge into the single-file shape, versioned and cache-first', async () => {
  const {fetchImpl, calls} = server({
    'L/tags-index.json': index,
    'L/shards/tags-aaaaaaaaaaaaaaaaaaaa.json': shard(0, {HB1: {summary: 'one'}}),
    'L/shards/tags-bbbbbbbbbbbbbbbbbbbb.json': shard(1, {SB2: {summary: 'two'}}),
  });
  const map = await loadShardedMap('L', 'tags', FORMAT, fetchImpl);
  assert.deepEqual(map, {model: 'm', generated_at: '2026-11-15T00:00:00Z', agencies: {A: 'Agency'}, format: FORMAT,
    bills: {HB1: {summary: 'one'}, SB2: {summary: 'two'}}});
  assert.deepEqual(calls.map(c => [c.url, c.cache]), [
    ['L/tags-index.json', 'no-cache'],
    ['L/shards/tags-aaaaaaaaaaaaaaaaaaaa.json', 'force-cache'],
    ['L/shards/tags-bbbbbbbbbbbbbbbbbbbb.json', 'force-cache']]);
});

test('anything off about the shards throws so the caller falls back to the single file', async () => {
  const good = {'L/tags-index.json': index, 'L/shards/tags-aaaaaaaaaaaaaaaaaaaa.json': shard(0, {}), 'L/shards/tags-bbbbbbbbbbbbbbbbbbbb.json': shard(1, {})};
  const cases = [
    {...good, 'L/tags-index.json': undefined},
    {...good, 'L/tags-index.json': {...index, of: 'texas-bill-luna-extras-v1'}},
    {...good, 'L/tags-index.json': {...index, shards: []}},
    {...good, 'L/tags-index.json': {...index, shards: ['../x']}},
    {...good, 'L/shards/tags-bbbbbbbbbbbbbbbbbbbb.json': undefined},
    {...good, 'L/shards/tags-bbbbbbbbbbbbbbbbbbbb.json': shard(0, {})},
    {...good, 'L/shards/tags-bbbbbbbbbbbbbbbbbbbb.json': {...shard(1, {}), of: 'other'}},
    {...good, 'L/shards/tags-bbbbbbbbbbbbbbbbbbbb.json': shard(1, [])},
  ];
  for (const files of cases) {
    for (const k of Object.keys(files)) if (files[k] === undefined) delete files[k];
    await assert.rejects(loadShardedMap('L', 'tags', FORMAT, server(files).fetchImpl));
  }
});
