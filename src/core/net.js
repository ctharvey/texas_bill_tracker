export const timeoutSignal = ms => {if(typeof AbortSignal!=='undefined'&&typeof AbortSignal.timeout==='function')return AbortSignal.timeout(ms);const c=new AbortController();setTimeout(()=>c.abort(),ms);return c.signal};
// A response the caller will not read: cancel its body, or the request stays open until its timeout signal fires
// (an unread 404 held each E2E page load for 20 s; tests/net_release.test.mjs).
export function discard(response){try{response?.body?.cancel()?.catch?.(()=>{})}catch{}return null}
export const httpError = response => (discard(response), Error(`HTTP ${response.status}`));

const isMap = o => Boolean(o) && typeof o === 'object' && !Array.isArray(o);
// A large Luna map published as content-addressed shards (scripts/luna_shards.py): the small index lists each
// shard's file name, which is the hash of its bytes and never rewritten, so a shard comes from the browser cache
// with no request and no cache can hold other bytes under its name.
// Returns the map shaped like the single file ({...index fields, format, bills}); throws if anything is off, so the
// caller can fall back to the single file.
export async function loadShardedMap(base, name, format, fetchImpl = fetch, ms = 20000) {
  const response = await fetchImpl(`${base}/${name}-index.json`, {cache: 'no-cache', signal: timeoutSignal(ms)});
  if (!response.ok) throw httpError(response);
  const index = await response.json();
  const versions = index?.shards;
  if (index?.format !== 'texas-bill-luna-shards-v2' || index.of !== format || !Array.isArray(versions) || !versions.length
    || !versions.every(v => typeof v === 'string' && /^[0-9a-f]{20}$/.test(v))) throw Error('Unrecognized shard index');
  const parts = await Promise.all(versions.map(async (v, n) => {
    const r = await fetchImpl(`${base}/shards/${name}-${v}.json`, {cache: 'force-cache', signal: timeoutSignal(ms)});
    if (!r.ok) throw httpError(r);
    const part = await r.json();
    if (part?.format !== 'texas-bill-luna-shard-v1' || part.of !== format || part.shard !== n || !isMap(part.bills))
      throw Error('Unrecognized shard');
    return part.bills;
  }));
  const {shards: _s, of: _o, ...rest} = index;
  return {...rest, format, bills: Object.assign({}, ...parts)};
}
