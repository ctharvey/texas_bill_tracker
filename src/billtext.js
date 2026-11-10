const MAX_BYTES = 8 * 1024 * 1024;
const TAGS = {'<ins>': ['open', 'ins'], '</ins>': ['close', 'ins'], '<del>': ['open', 'del'], '</del>': ['close', 'del']};
const TAG_RE = /^<\/?(?:ins|del)>/;
const KINDS = ['agency', 'effect', 'topic', 'group', 'location', 'summary', 'scope'];
const CHIPS = [['agency', 'Agencies'], ['effect', 'Effects'], ['topic', 'Topics'], ['group', 'Groups'],
    ['location', 'Locations'], ['summary', 'Summary']];
const chipOf = kind => kind === 'scope' ? 'agency' : kind; // the all-agencies scope marker toggles with Agencies

function parseParagraph(line, index) {
    let heading = false, level = 0, body = line;
    if (body.startsWith('### ')) { heading = true; level = 3; body = body.slice(4); }
    else if (index === 0 && body.startsWith('# ')) { heading = true; level = 1; body = body.slice(2); }
    const segments = [];
    let mark = null, buffer = '';
    const flush = () => { if (buffer) segments.push({text: buffer, mark}); buffer = ''; };
    for (let i = 0; i < body.length;) {
        const ch = body[i];
        if (ch === '\\' && i + 1 < body.length) {
            const point = body.codePointAt(i + 1), width = point > 0xffff ? 2 : 1;
            buffer += body.slice(i + 1, i + 1 + width); i += 1 + width; continue;
        }
        if (ch === '<') {
            const m = TAG_RE.exec(body.slice(i, i + 6));
            if (m) {
                const [kind, name] = TAGS[m[0]];
                if (kind === 'open') {
                    if (mark) throw Error('Nested tags in bill text');
                    flush(); mark = name;
                } else {
                    if (mark !== name) throw Error('Unbalanced tags in bill text');
                    flush(); mark = null;
                }
                i += m[0].length; continue;
            }
        }
        buffer += ch; i++;
    }
    if (mark) throw Error('Unbalanced tags in bill text');
    flush();
    return {heading, level, segments, plain: segments.map(s => s.text).join('')};
}

export function parseBillMarkdown(md) {
    if (typeof md !== 'string' || md.length > MAX_BYTES) throw Error('Bill text is too large');
    const lines = md.split('\n').map(l => l.endsWith('\r') ? l.slice(0, -1) : l).filter(l => l.trim() !== '');
    const paragraphs = lines.map(parseParagraph);
    return {title: paragraphs[0]?.plain || '', paragraphs};
}

const validRange = (r, length) => r && Number.isInteger(r.start) && Number.isInteger(r.end)
    && r.start >= 0 && r.end > r.start && r.end <= length;

export function paragraphSegments(paragraph, ranges = []) {
    const total = Array.from(paragraph.plain).length;
    const good = ranges.filter(r => validRange(r, total));
    const pieces = [];
    let offset = 0;
    for (const s of paragraph.segments) {
        const points = Array.from(s.text);
        pieces.push({points, mark: s.mark, start: offset, end: offset + points.length});
        offset += points.length;
    }
    const bounds = new Set([0, total]);
    pieces.forEach(p => { bounds.add(p.start); bounds.add(p.end); });
    good.forEach(r => { bounds.add(r.start); bounds.add(r.end); });
    const sorted = [...bounds].sort((a, b) => a - b), out = [];
    for (let i = 0; i < sorted.length - 1; i++) {
        const start = sorted[i], end = sorted[i + 1];
        const piece = pieces.find(p => p.start <= start && p.end >= end);
        if (!piece) continue;
        const ids = [...new Set(good.filter(r => r.start < end && r.end > start).map(r => r.id))];
        out.push({text: piece.points.slice(start - piece.start, end - piece.start).join(''), mark: piece.mark, ids});
    }
    return out;
}

export function validHighlights(h, billId, versionCode, sha) {
    return Boolean(h) && typeof h === 'object' && h.format === 'texas-bill-luna-highlights-v1'
        && h.bill_id === billId && h.text_version === versionCode
        && typeof sha === 'string' && h.text_sha256 === sha && Array.isArray(h.claims);
}

export async function sha256Hex(text) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// opts: {highlightsNote?: string, idPrefix?: string}
export function renderBillText(root, parsed, highlights, opts = {}) {
    const node = (tag, text, className) => {
        const el = document.createElement(tag);
        if (text !== undefined) el.textContent = text;
        if (className) el.className = className;
        return el;
    };
    const prefix = opts.idPrefix || 'bt';
    root.replaceChildren(); root.className = 'bill-text';
    const claims = new Map(), byParagraph = new Map();
    if (highlights) {
        for (const c of highlights.claims) {
            if (!c || typeof c.id !== 'string' || !KINDS.includes(c.kind)) continue;
            claims.set(c.id, c);
            for (const r of Array.isArray(c.ranges) ? c.ranges : []) {
                if (!r || !Number.isInteger(r.p) || !parsed.paragraphs[r.p]) continue;
                if (!byParagraph.has(r.p)) byParagraph.set(r.p, []);
                byParagraph.get(r.p).push({start: r.start, end: r.end, id: c.id});
            }
        }
    }
    const legend = node('p', undefined, 'bt-legend');
    legend.append(node('ins', 'Underlined'), ' = added by the bill · ', node('del', 'struck through'), ' = removed');
    if (claims.size) legend.append(' · highlight colours show the kind of Luna note (select a highlight to read it)');
    const filters = {kinds: new Set(CHIPS.map(c => c[0])), agency: ''};
    const panel = node('div', undefined, 'bt-panel');
    panel.setAttribute('aria-live', 'polite');
    const body = node('div', undefined, 'bt-body');
    const firstMark = new Map(), marks = [];
    const visible = c => c && filters.kinds.has(chipOf(c.kind)) && (!filters.agency || (c.agency_id || c.id) === filters.agency);
    const refresh = () => marks.forEach(m => {
        const ids = m.dataset.ids.split(' ').filter(id => visible(claims.get(id)));
        m.classList.toggle('hl-off', !ids.length);
        if (ids.length) m.dataset.kind = claims.get(ids[0]).kind;
    });
    function explain(ids) {
        panel.replaceChildren();
        ids.map(id => claims.get(id)).filter(Boolean).forEach(c => {
            const box = node('div', undefined, 'bt-claim');
            const detail = [c.kind, c.impact, c.effect].filter(Boolean).join(' · ');
            box.append(node('strong', c.label || c.id), node('small', detail), node('p', c.explanation || ''));
            panel.append(box);
        });
    }
    if (!claims.size) {
        root.append(legend, node('p', opts.highlightsNote || 'Luna highlights appear after the full-text review.', 'bt-note'));
    } else {
        const keys = [...claims.values()].filter(c => c.key_point);
        const bar = node('div', undefined, 'bt-tools');
        if (keys.length) {
            const box = node('div', undefined, 'bt-keys');
            box.append(node('strong', 'Key points'));
            const list = node('ul');
            keys.forEach(c => {
                const li = node('li'), b = node('button', c.label || c.id, 'bt-key');
                b.type = 'button';
                b.addEventListener('click', () => {
                    if (!filters.kinds.has(chipOf(c.kind)) || (filters.agency && (c.agency_id || c.id) !== filters.agency)) {
                        filters.kinds.add(chipOf(c.kind)); filters.agency = ''; syncControls();
                    }
                    const m = firstMark.get(c.id);
                    if (!m) return;
                    refresh(); m.scrollIntoView({block: 'center', behavior: 'smooth'});
                    explain([c.id]); m.classList.add('hl-flash');
                    setTimeout(() => m.classList.remove('hl-flash'), 1600);
                });
                li.append(b); list.append(li);
            });
            box.append(list); bar.append(box);
        }
        const chips = node('div', undefined, 'bt-chips');
        const present = new Set([...claims.values()].map(c => chipOf(c.kind)));
        const chipButtons = [];
        CHIPS.filter(([k]) => present.has(k)).forEach(([kind, label]) => {
            const b = node('button', label, `bt-chip hl-${kind}`);
            b.type = 'button'; b.setAttribute('aria-pressed', 'true');
            b.addEventListener('click', () => {
                if (filters.kinds.has(kind)) filters.kinds.delete(kind); else filters.kinds.add(kind);
                syncControls();
            });
            chips.append(b); chipButtons.push([kind, b]);
        });
        bar.append(chips);
        const agencies = new Map();
        [...claims.values()].filter(c => c.kind === 'agency').forEach(c => agencies.set(c.agency_id || c.id, c.label || c.id));
        let select = null;
        if (agencies.size) {
            const wrap = node('label', 'Agency ', 'bt-agency');
            select = node('select');
            select.append(Object.assign(node('option', 'All agencies'), {value: ''}));
            [...agencies].sort((a, b) => a[1].localeCompare(b[1])).forEach(([key, label]) =>
                select.append(Object.assign(node('option', label), {value: key})));
            select.addEventListener('change', () => { filters.agency = select.value; syncControls(); });
            wrap.append(select); bar.append(wrap);
        }
        function syncControls() {
            chipButtons.forEach(([kind, b]) => b.setAttribute('aria-pressed', String(filters.kinds.has(kind))));
            if (select) select.value = filters.agency;
            refresh();
        }
        root.append(legend, bar, panel);
    }
    parsed.paragraphs.forEach((paragraph, index) => {
        const el = paragraph.heading ? node('h4') : node('p');
        if (paragraph.heading) el.id = `${prefix}-p${index}`;
        for (const seg of paragraphSegments(paragraph, byParagraph.get(index) || [])) {
            let target = el;
            if (seg.mark) { target = node(seg.mark); el.append(target); }
            if (!seg.ids.length) { target.append(document.createTextNode(seg.text)); continue; }
            const first = claims.get(seg.ids[0]);
            const m = node('mark', seg.text, `hl hl-${first.kind}${seg.ids.some(id => claims.get(id)?.key_point) ? ' hl-key' : ''}`);
            m.dataset.ids = seg.ids.join(' '); m.dataset.kind = first.kind;
            m.tabIndex = 0;
            m.addEventListener('click', () => explain(seg.ids));
            m.addEventListener('keydown', e => { if (e.key === 'Enter') explain(seg.ids); });
            marks.push(m);
            seg.ids.forEach(id => { if (!firstMark.has(id)) firstMark.set(id, m); });
            target.append(m);
        }
        body.append(el);
    });
    root.append(body);
}
