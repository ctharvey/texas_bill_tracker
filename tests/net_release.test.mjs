import test from 'node:test';
import assert from 'node:assert/strict';
import {loadShardedMap, httpError, discard} from '../src/core/net.js';

// A failed response nobody reads keeps its request open until the timeout signal fires (20 s in E2E, where three
// such 404s held every page's networkidle). Each failure path must cancel the body.
const failed = status => {
  const r = {ok: false, status, cancelled: 0, json: async () => null};
  r.body = {cancel: async () => { r.cancelled++; }};
  return r;
};

test('httpError cancels the body and names the status', () => {
  const r = failed(404);
  const error = httpError(r);
  assert.equal(error.message, 'HTTP 404');
  assert.equal(r.cancelled, 1);
});

test('discard cancels the body and returns null', () => {
  const r = failed(500);
  assert.equal(discard(r), null);
  assert.equal(r.cancelled, 1);
});

test('discard tolerates responses without a body or with a failing cancel', () => {
  assert.equal(discard({ok: false, status: 404}), null);
  assert.equal(discard({ok: false, status: 404, body: null}), null);
  assert.equal(discard({ok: false, status: 404, body: {cancel: () => Promise.reject(Error('locked'))}}), null);
  assert.equal(discard({ok: false, status: 404, body: {cancel: () => { throw Error('locked'); }}}), null);
});

test('loadShardedMap cancels a missing index body before falling back', async () => {
  const index = failed(404);
  await assert.rejects(loadShardedMap('L', 'tags', 'f', async () => index), /HTTP 404/);
  assert.equal(index.cancelled, 1);
});

test('loadShardedMap cancels a missing shard body', async () => {
  const shard = failed(404);
  const fetchImpl = async url => url.endsWith('-index.json')
    ? {ok: true, status: 200, json: async () => ({format: 'texas-bill-luna-shards-v2', of: 'f', shards: ['0123456789abcdef0123']})}
    : shard;
  await assert.rejects(loadShardedMap('L', 'tags', 'f', fetchImpl), /HTTP 404/);
  assert.equal(shard.cancelled, 1);
});
