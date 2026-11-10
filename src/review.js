const claimAt = (result, label) => {
    if (label === 'summary') return {label: 'Summary', value: result.summary};
    const [field, rawIndex] = label.split(':');
    if (!['policy_tags', 'agencies', 'locations', 'affected_groups', 'major_effects'].includes(field)) return null;
    if (!/^\d+$/.test(rawIndex)) return null;
    const value = result[field]?.[Number(rawIndex)];
    if (!value) return null;
    const names = {policy_tags:'Policy tag', agencies:'Agency', locations:'Location',
        affected_groups:'Affected group', major_effects:'Major effect'};
    return {label: `${names[field]}: ${value.tag || value.name || value.group || value.label}`, value};
};

export function reviewModel(bundle) {
    const {document: source, result, validation} = bundle;
    if (bundle.format !== 'texas-bill-review-v1' || !/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}$/.test(bundle.bill_id)
        || source?.bill_id !== bundle.bill_id || source.session !== '90R' || result?.bill_id !== bundle.bill_id
        || !Array.isArray(source.pages) || !source.pages.length || source.pages.some(p => typeof p !== 'string')
        || source.pages.join('').length > 2_000_000 || !Array.isArray(validation?.verified_citations)) {
        throw Error('This file is not a complete Texas bill review');
    }
    const pages = source.pages.map(p => Array.from(p)); // Python offsets count Unicode code points.
    const annotations = [];
    const corrected = new Set();
    for (const resolution of bundle.resolutions || []) {
        if (resolution.result?.status !== 'resolved') continue;
        for (const correction of resolution.result.corrections || []) corrected.add(correction.claim);
    }
    for (const citation of validation.verified_citations) {
        if (citation.status !== 'resolved') continue;
        const claim = claimAt(result, citation.claim);
        if (!claim) throw Error('A citation refers to an unknown classification');
        for (const part of citation.parts || []) {
            const page = pages[part.page - 1];
            if (!page || !Number.isInteger(part.start) || !Number.isInteger(part.end) || part.start < 0
                || part.end <= part.start || part.end > page.length
                || page.slice(part.start, part.end).join('') !== part.quote) {
                throw Error('A highlighted excerpt does not match the supplied source text');
            }
        }
        annotations.push({label: claim.label, why: claim.value.text || claim.value.explanation,
            kind: citation.claim.startsWith('agencies:') ? 'agency' : corrected.has(citation.claim) ? 'reviewed' : 'tag',
            impact: claim.value.impact, corrected: corrected.has(citation.claim),
            parts: citation.parts || [], external: citation.source_url ? citation : null});
    }
    return {pages, annotations, summary: result.summary.text, questions: bundle.pending_questions || [],
        status: bundle.status || 'needs_review', errors: validation.errors || [], version: source.version,
        textHash: source.text_hash, sourceUrl: source.source_url};
}

export function pageSegments(points, annotations, pageNumber) {
    const ranges = [];
    annotations.forEach((annotation, id) => annotation.parts.forEach(p => {
        if (p.page === pageNumber) ranges.push({...p, id, kind: annotation.kind});
    }));
    const bounds = [...new Set([0, points.length, ...ranges.flatMap(p => [p.start, p.end])])].sort((a,b) => a-b);
    return bounds.slice(0,-1).map((start, i) => {
        const end = bounds[i+1], active = ranges.filter(p => p.start < end && p.end > start);
        return {text: points.slice(start,end).join(''), ids: [...new Set(active.map(p => p.id))],
            kind: active.some(p => p.kind === 'agency') ? 'agency' : active.some(p => p.kind === 'reviewed') ? 'reviewed' : 'tag'};
    });
}

function safeSourceUrl(value) {
    try {
        const url = new URL(value);
        if ((url.protocol === 'https:' && ['tcss.legis.texas.gov','statutes.capitol.texas.gov'].includes(url.hostname))
            || (url.protocol === 'ftp:' && url.hostname === 'ftp.legis.state.tx.us')) {
            return url.href;
        }
    } catch {}
    return null;
}

export function renderReview(root, bundle, privateImport = false) {
    const model = reviewModel(bundle);
    const node = (tag, text, className) => {
        const el = document.createElement(tag);
        if (text !== undefined) el.textContent = text;
        if (className) el.className = className;
        return el;
    };
    root.replaceChildren(); root.className = 'bill-review';
    root.append(node('p', `${privateImport ? 'Private import · ' : ''}${model.status.replaceAll('_',' ')} · `
        + `${model.version} text · ${model.pages.length} PDF pages`, 'review-status'));
    root.append(node('p', model.summary, 'review-summary'));
    if (model.errors.length) root.append(node('p', 'Validation issues remain. This analysis needs review.', 'review-warning'));
    if (model.questions.length) {
        const details = node('details'); details.append(node('summary', `${model.questions.length} open review questions`));
        const list = node('ul');
        model.questions.forEach(q => list.append(node('li', `${q.question} (${q.reason || 'Unresolved'})`)));
        details.append(list); root.append(details);
    }
    root.append(node('p', 'Select highlighted text to see why it matters. Agency links, other classifications, '
        + 'and reviewed descriptions use separate highlights.', 'review-help'));
    const legend = node('div', undefined, 'review-legend');
    for (const [kind, label] of [['agency','Agency impact'],['tag','Tags & scope'],['reviewed','Reviewed description']]) {
        legend.append(node('span',label,`review-key review-${kind}`));
    }
    root.append(legend);
    const explanation = node('div', undefined, 'review-explanation');
    explanation.setAttribute('aria-live','polite');
    root.append(explanation);
    function select(ids, text, page, scroll = false) {
        explanation.replaceChildren(node('strong', `Why highlighted · PDF page ${page}`), node('blockquote',text));
        const seen = new Set();
        ids.forEach(id => {
            const a = model.annotations[id];
            if (seen.has(a.label)) return;
            seen.add(a.label);
            explanation.append(node('h4', a.label + (a.impact ? ` · ${a.impact}` : '')), node('p',a.why));
            if (a.corrected) explanation.append(node('small','Refined during targeted source review.'));
        });
        if (scroll) explanation.scrollIntoView({block:'nearest'});
    }
    model.pages.forEach((points,index) => {
        const details = node('details',undefined,'review-page'); details.open = index === 0;
        details.append(node('summary',`PDF page ${index+1}`));
        const paragraph = node('p',undefined,'review-source');
        for (const segment of pageSegments(points,model.annotations,index+1)) {
            if (!segment.ids.length) { paragraph.append(document.createTextNode(segment.text)); continue; }
            const button = node('button',segment.text,`review-highlight review-${segment.kind}`);
            button.type = 'button'; button.setAttribute('aria-label',`${segment.text} — why highlighted`);
            button.addEventListener('click',() => select(segment.ids,segment.text,index+1,true));
            paragraph.append(button);
        }
        details.append(paragraph); root.append(details);
    });
    const external = model.annotations.filter(a => a.external);
    if (external.length) {
        const details = node('details'); details.append(node('summary','Supporting statutory definitions'));
        external.forEach(a => {
            details.append(node('h4',a.label),node('blockquote',a.external.quote));
            const url = safeSourceUrl(a.external.source_url);
            if (url) {
                const link = node('a',`Official source · ${a.external.section || 'Statute'}`,'text-link');
                link.href=url; link.target='_blank'; link.rel='noopener noreferrer'; details.append(link);
            }
        }); root.append(details);
    }
    const first = model.annotations.find(a => a.parts.length);
    if (first) select([model.annotations.indexOf(first)],first.parts[0].quote,first.parts[0].page);
    root.append(node('p','Highlights show supporting excerpts, not an exhaustive legal analysis. '
        + 'Offsets refer to normalized PDF text. Verify the current official text before relying on a classification.', 'review-help'));
}

// Bill text (Markdown) rendering. Kept in this module because the static deployer ships a fixed file list.
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
