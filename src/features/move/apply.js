// Receiver side of a move: plan against this site's data, then add through the app's own change paths (so a browser
// with a sync link queues each addition to it), keep held items, join or keep the incoming link, and read back.
import {receive, plan, verify, keepHeld, keepPreviousLink} from '../../core/move.js';

// deps: storage, current() -> this site's state for plan(), addWatch(ids), addFollows(codes), addSearch(search),
// setSettings(settings), joinLink(editKey) (connect, then a merging pull).
export async function applyMove(payload, deps) {
  const cleaned = receive(payload);
  const planned = plan(deps.current(), cleaned);
  keepHeld(deps.storage, planned.held);
  if (planned.watch.length) deps.addWatch(planned.watch);
  if (planned.follows.length) deps.addFollows(planned.follows);
  for (const s of planned.searches) deps.addSearch(s);
  if (Object.keys(planned.settings).length) deps.setSettings(planned.settings);
  if (planned.sync === 'keep-previous') keepPreviousLink(deps.storage, planned.editKey);
  if (planned.sync === 'join') await deps.joinLink(planned.editKey);
  const checked = verify(deps.storage, cleaned, planned);
  const held = planned.held.watch.length + planned.held.follows.length + planned.held.searches.length;
  return {
    ok: checked.ok,
    counts: {watch: planned.watch.length, follows: planned.follows.length, searches: planned.searches.length,
      settings: Object.keys(planned.settings).length, held, sync: planned.sync},
    previousKey: planned.sync === 'keep-previous' ? planned.editKey : null,  // Shown here only; never sent back.
  };
}
