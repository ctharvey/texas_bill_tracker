// Text for an AI assistant: "Copy for AI" and "Ask ChatGPT / Claude" on a bill, "Copy page for AI" for the view on screen.
import {companionLabel, lastActionInfo, officialUrl} from '../../taxonomy.js';

export const AGENT_BASE = 'https://agent.billatlas.org/';
export const TEXT_BASE = 'https://billatlas.org/live/text/';
export const agentUrl = bill => `${AGENT_BASE}bills/${encodeURIComponent(bill.id || String(bill.number || '').replace(/\s+/g, ''))}.md`;
const httpsUrl = value => { try { const u = new URL(String(value)); return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : ''; } catch { return ''; } };

// Text for pasting into an AI assistant: where to read the bill, and one neutral instruction.
export function aiPrompt(bill, companions = []) {
  const versions = Array.isArray(bill.text_versions) ? bill.text_versions.filter(v => v && httpsUrl(v.html)) : [];
  const latest = versions[versions.length - 1];
  const textLine = latest
    ? `Official bill text${latest.name ? ` (${latest.name})` : ''}: ${httpsUrl(latest.html)}`
    : `Official bill history and text: ${officialUrl(bill)}`;
  // Our Markdown copy of the same file (live/text, written by sync_ftp.py): capitol.texas.gov often refuses AI fetchers.
  // The snapshot's version links are ftp://, which httpsUrl drops, so the copy goes by version code alone.
  const coded = (Array.isArray(bill.text_versions) ? bill.text_versions : []).filter(v => v && /^[A-Za-z0-9]{1,8}$/.test(String(v.code || '')));
  const last = coded[coded.length - 1];
  const copy = last && bill.id
    ? [`Full bill text${last.name ? ` (${last.name})` : ''}, the official wording as Markdown: ${TEXT_BASE}${encodeURIComponent(bill.id)}/${last.code}.md`] : [];
  return [`Texas ${bill.number} (90th Legislature): ${bill.title}`, '',
    `AI-readable version with history and review: ${agentUrl(bill)}`, ...copy, textLine,
    ...companions.map(c => `Companion bill ${companionLabel(c)}: ${agentUrl(c)}`), '',
    // Some assistants (Claude on the web) won't open links that arrive in a prefilled prompt but will open pages
    // their own web search finds, so name the site and bill as a search too.
    `If you can't open these links, search the web for "Texas Bill Atlas ${bill.number}" (billatlas.org) and use its bill page and the official Texas Legislature pages. Earlier sessions reused this bill number: use only the 90th Legislature (2027) bill.`,
    'Summarize what this bill does, who it affects, and its current status, citing the bill text.'].join('\n');
}

// "Ask ChatGPT / Claude": the same prompt, prefilled through each assistant's ?q= link. Neither link is a documented
// API, so the bill page keeps "Copy for AI" as the dependable path.
export const AI_CHATS = [['ChatGPT', 'https://chatgpt.com/?q='], ['Claude', 'https://claude.ai/new?q=']];
export const aiChatLinks = (bill, companions = []) => {
  const q = encodeURIComponent(aiPrompt(bill, companions));
  return AI_CHATS.map(([name, base]) => ({name, href: base + q}));
};

// ---- "Copy page for AI": the view on screen as text an AI assistant can follow ----
export const AI_LIST_LIMIT = 50;
const VIEW_PAGES = {home: ['Home', 'index.md'], agencies: ['Agency index', 'agencies/index.md'], review: ['Full-text review progress', 'review-progress.md'],
  method: ['How it works', 'llms.txt'], saving: ['Saving your info', 'saving.md'], data: ['Data & imports', 'llms.txt']};

// ctx: {view, label, pageUrl, bill, bills, filters:{query,topic,agency,chamber}, agencyName, day,
//       companions: id -> [companion entries], via: Map(id -> [companion ids]) for bills listed through a companion}
export function pageAiText(ctx) {
  const companions = ctx.companions || (() => []);
  if (ctx.bill) return aiPrompt(ctx.bill, companions(ctx.bill.id));
  const f = ctx.filters || {};
  const lines = [];
  if (VIEW_PAGES[ctx.view]) {
    const [title, path] = VIEW_PAGES[ctx.view];
    lines.push(`Texas Bill Atlas (90th Legislature): ${title}`, `Page: ${ctx.pageUrl}`, '',
      `AI-readable version: ${AGENT_BASE}${path}`, `Everything available: ${AGENT_BASE}llms.txt`, '',
      'Use these links to answer my questions about Texas bills; open a bill\'s page for its details.');
    return lines.join('\n');
  }
  const described = [f.query && `search "${f.query}"`, f.topic && `topic ${f.topic}`,
    f.agency && `agency ${ctx.agencyName ? ctx.agencyName(f.agency) : f.agency}`, f.chamber && `chamber ${f.chamber}`].filter(Boolean);
  const params = new URLSearchParams();
  if (f.query) params.set('q', f.query);
  if (f.topic) params.set('topic', f.topic);
  if (f.agency) params.set('agency', f.agency);
  if (f.chamber) params.set('chamber', f.chamber);
  const search = [...params].length ? `${AGENT_BASE}search?${params}` : null;
  const bills = ctx.bills || [];
  lines.push(`Texas Bill Atlas (90th Legislature): ${ctx.label}${ctx.day ? ` for ${ctx.day}` : ''}${described.length ? ` (${described.join(', ')})` : ''}`,
    `Page: ${ctx.pageUrl}`, `${bills.length} ${bills.length === 1 ? 'bill' : 'bills'} shown.`, '');
  const viaShown = bills.some(b => ctx.via?.has(b.id));
  if (search) lines.push(`${viaShown ? 'Bills tagged with this agency directly (companions not added), AI-readable' : 'Same list, AI-readable'}: ${search}`);
  lines.push(`Everything available: ${AGENT_BASE}llms.txt`, '');
  for (const b of bills.slice(0, AI_LIST_LIMIT)) {
    const last = lastActionInfo(b);
    const comp = companions(b.id), via = ctx.via?.get(b.id);
    lines.push(`- ${b.number}: ${b.title}${b.headline ? ` | In brief: ${b.headline}` : ''} | Last action: ${last.text || last.label}${last.date ? ` (${last.date})` : ''}`
      + `${comp.length ? ` | Companion: ${comp.map(companionLabel).join(', ')}` : ''}`
      + `${via ? ` | Listed because its companion ${via.map(id => companionLabel({id})).join(', ')} is tagged with this agency` : ''} | ${agentUrl(b)}`);
  }
  if (bills.length > AI_LIST_LIMIT) lines.push(`- ...and ${bills.length - AI_LIST_LIMIT} more${search ? `; the full list is at ${search}` : ' (open the page link for the rest)'}.`);
  lines.push('', 'Use these links to answer my questions about these bills; open a bill\'s page for its full details.');
  return lines.join('\n');
}
