// The move hand-off between two open windows: the old site's page (sender) and the new site's page it opened
// (receiver). Each side accepts messages only from the one window and origin it expects, and the receiver only one
// data message, carrying the nonce it chose. Windows are passed in, so tests use fakes.

// Sender. `win` was opened inside the click (window.open). Resolves {ok, counts} on a verified result, or
// {ok:false, reason} when the window closed, timed out, or reported a failure. `getPayload` runs after `ready`.
export function sendMove({self, win, target, getPayload, timeoutMs = 30000, pollMs = 500, timers = globalThis}) {
  return new Promise(resolve => {
    let nonce = null, sent = false, finished = false;
    const finish = result => {
      if (finished) return;
      finished = true;
      self.removeEventListener('message', onMessage);
      timers.clearInterval(poll); timers.clearTimeout(timer);
      resolve(result);
    };
    async function onMessage(e) {
      if (e.source !== win || e.origin !== target || !e.data || typeof e.data !== 'object') return;
      const {type} = e.data;
      if (type === 'move-ready' && !sent && typeof e.data.nonce === 'string' && e.data.nonce.length >= 16) {
        sent = true; nonce = e.data.nonce;
        let payload;
        try { payload = await getPayload(); } catch { finish({ok: false, reason: 'read'}); return; }
        if (!finished) win.postMessage({type: 'move-data', nonce, payload}, target);
      } else if (type === 'move-done' && sent && e.data.nonce === nonce) {
        finish(e.data.ok === true ? {ok: true, counts: e.data.counts || {}} : {ok: false, reason: 'failed', counts: e.data.counts || {}});
      }
    }
    self.addEventListener('message', onMessage);
    const poll = timers.setInterval(() => { if (win.closed) finish({ok: false, reason: 'closed'}); }, pollMs);
    const timer = timers.setTimeout(() => finish({ok: false, reason: 'timeout'}), timeoutMs);
  });
}

// Receiver. Posts `ready` to its opener, applies the one matching data message with `apply(payload)` (which returns
// {ok, counts}), and reports back. Resolves with apply's result, or {ok:false, reason:'timeout'}.
export function receiveMove({self, opener, source, apply, nonce, timeoutMs = 30000, timers = globalThis}) {
  return new Promise(resolve => {
    let taken = false;
    const timer = timers.setTimeout(() => { if (!taken) { self.removeEventListener('message', onMessage); resolve({ok: false, reason: 'timeout'}); } }, timeoutMs);
    async function onMessage(e) {
      if (taken || e.source !== opener || e.origin !== source || e.data?.type !== 'move-data' || e.data.nonce !== nonce) return;
      taken = true;
      self.removeEventListener('message', onMessage);
      timers.clearTimeout(timer);
      let result;
      try { result = await apply(e.data.payload); } catch { result = {ok: false, counts: {}}; }
      try { opener.postMessage({type: 'move-done', nonce, ok: result.ok === true, counts: result.counts || {}}, source); } catch {}
      resolve(result);
    }
    self.addEventListener('message', onMessage);
    opener.postMessage({type: 'move-ready', nonce}, source);
  });
}

export const newNonce = (cryptoImpl = globalThis.crypto) =>
  [...cryptoImpl.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
