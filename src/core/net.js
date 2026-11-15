export const timeoutSignal = ms => {if(typeof AbortSignal!=='undefined'&&typeof AbortSignal.timeout==='function')return AbortSignal.timeout(ms);const c=new AbortController();setTimeout(()=>c.abort(),ms);return c.signal};

const isMap = o => Boolean(o) && typeof o === 'object' && !Array.isArray(o);
// A large Luna map published as content-addressed shards (scripts/luna_shards.py): the small index names each
// shard's hash and the shard URL carries it, so an unchanged shard comes from the browser cache with no request.
// Returns the map shaped like the single file ({...index fields, format, bills}); throws if anything is off, so the
// caller can fall back to the single file.
export async function loadShardedMap(base, name, format, fetchImpl = fetch, ms = 20000) {
  const response = await fetchImpl(`${base}/${name}-index.json`, {cache: 'no-cache', signal: timeoutSignal(ms)});
  if (!response.ok) throw Error(`HTTP ${response.status}`);
  const index = await response.json();
  const versions = index?.shards;
  if (index?.format !== 'texas-bill-luna-shards-v1' || index.of !== format || !Array.isArray(versions) || !versions.length
    || !versions.every(v => typeof v === 'string' && /^[0-9a-f]{8,64}$/.test(v))) throw Error('Unrecognized shard index');
  const parts = await Promise.all(versions.map(async (v, n) => {
    const r = await fetchImpl(`${base}/shards/${name}-${n}.json?v=${v}`, {cache: 'force-cache', signal: timeoutSignal(ms)});
    if (!r.ok) throw Error(`HTTP ${r.status}`);
    const part = await r.json();
    if (part?.format !== 'texas-bill-luna-shard-v1' || part.of !== format || part.shard !== n || !isMap(part.bills))
      throw Error('Unrecognized shard');
    return part.bills;
  }));
  const {shards: _s, of: _o, ...rest} = index;
  return {...rest, format, bills: Object.assign({}, ...parts)};
}
