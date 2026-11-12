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

// ---- Drawer stages: what changed, hearing witnesses, fiscal note check ----
const stageNode = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
};
const strings = list => (Array.isArray(list) ? list : []).filter(q => typeof q === 'string' && q);
const quotesBlock = (label, quotes) => {
    const q = strings(quotes);
    if (!q.length) return null;
    const details = stageNode('details', undefined, 'stage-quotes');
    details.append(stageNode('summary', label));
    q.forEach(text => details.append(stageNode('blockquote', text)));
    return details;
};
const newestVersion = index => {
    const list = Array.isArray(index?.versions) ? index.versions.filter(v => v && typeof v.code === 'string') : [];
    return list.length ? list[list.length - 1] : null;
};

export function validChanges(data, billId, index) {
    if (!data || typeof data !== 'object' || data.format !== 'texas-bill-luna-changes-v1') return false;
    if (data.bill_id !== billId || !Array.isArray(data.changes) || !data.changes.length) return false;
    const newest = newestVersion(index);
    return Boolean(newest) && index.bill_id === billId && data.to_version === newest.code
        && typeof newest.sha256 === 'string' && data.text_sha256 === newest.sha256;
}

const CHANGE_KINDS = {added: 'Added', removed: 'Removed', altered: 'Changed'};

export function renderChanges(data, index) {
    const names = new Map((Array.isArray(index?.versions) ? index.versions : []).filter(v => v && v.code).map(v => [v.code, v.name || v.code]));
    const section = stageNode('section', undefined, 'drawer-section stage-section stage-changes');
    section.append(stageNode('h3', 'What changed'));
    section.append(stageNode('p', `Changes from ${names.get(data.from_version) || data.from_version} to ${names.get(data.to_version) || data.to_version}, summarized by Luna from the bill text.`));
    const list = stageNode('ul', undefined, 'stage-list');
    for (const c of data.changes) {
        if (!c || typeof c.label !== 'string') continue;
        const kind = CHANGE_KINDS[c.kind] ? c.kind : 'altered';
        const li = stageNode('li');
        li.append(stageNode('span', CHANGE_KINDS[kind], `stage-badge stage-${kind}`), ' ', stageNode('strong', c.label));
        if (typeof c.explanation === 'string' && c.explanation) li.append(stageNode('p', c.explanation));
        const quotes = quotesBlock('Quoted text', c.quotes);
        if (quotes) li.append(quotes);
        list.append(li);
    }
    section.append(list);
    return section;
}

export function witnessSummary(list) {
    const out = {for: 0, against: 0, on: 0, testified: 0, registered: 0, total: 0,
        testifiedBy: {for: 0, against: 0, on: 0}, registeredBy: {for: 0, against: 0, on: 0}};
    for (const w of Array.isArray(list) ? list : []) {
        if (!w || typeof w !== 'object' || !['for', 'against', 'on'].includes(w.position)) continue;
        out.total++; out[w.position]++;
        if (w.testified === true) { out.testified++; out.testifiedBy[w.position]++; }
        else { out.registered++; out.registeredBy[w.position]++; }
    }
    return out;
}

const LEGIS_FTP = 'ftp://ftp.legis.state.tx.us/';

function validWitnesses(p) {
    return p && typeof p === 'object' && p.format === 'texas-bill-witnesses-v1'
        && ['H', 'S'].includes(p.chamber) && Array.isArray(p.witnesses) && p.witnesses.length > 0;
}

export function renderHearing(payloads) {
    const good = (Array.isArray(payloads) ? payloads : []).filter(validWitnesses);
    if (!good.length) return null;
    const section = stageNode('section', undefined, 'drawer-section stage-section stage-hearing');
    section.append(stageNode('h3', 'Hearing'));
    for (const p of good.sort((a, b) => (a.chamber === 'H' ? 0 : 1) - (b.chamber === 'H' ? 0 : 1))) {
        const s = witnessSummary(p.witnesses);
        const box = stageNode('div', undefined, 'evidence-card stage-chamber');
        box.append(stageNode('strong', `${p.chamber === 'H' ? 'House' : 'Senate'}${typeof p.committee === 'string' && p.committee ? ` · ${p.committee}` : ''}`));
        const hearing = [typeof p.hearing === 'string' ? p.hearing : '', ...strings(p.hearings).filter(h => h !== p.hearing)].filter(Boolean);
        if (hearing.length) box.append(stageNode('p', hearing.join(' · ')));
        box.append(stageNode('p', `${s.for} for · ${s.against} against · ${s.on} on`));
        box.append(stageNode('p', `${s.testified} testified, ${s.registered} registered without testifying`, 'stage-small'));
        const testified = p.witnesses.filter(w => w && w.testified === true);
        for (const [pos, label] of [['for', 'For'], ['against', 'Against'], ['on', 'On']]) {
            const rows = testified.filter(w => w.position === pos && typeof w.name === 'string');
            if (!rows.length) continue;
            box.append(stageNode('h4', `${label} (${rows.length})`));
            const ul = stageNode('ul', undefined, 'stage-list');
            rows.forEach(w => ul.append(stageNode('li', w.organization ? `${w.name} — ${w.organization}` : w.name)));
            box.append(ul);
        }
        const reg = p.witnesses.filter(w => w && w.testified !== true && ['for', 'against', 'on'].includes(w.position) && typeof w.name === 'string');
        if (reg.length) {
            const details = stageNode('details', undefined, 'stage-quotes');
            details.append(stageNode('summary', `Registered, not testifying (${reg.length})`));
            const ul = stageNode('ul', undefined, 'stage-list');
            reg.forEach(w => ul.append(stageNode('li', `${w.name}${w.organization ? ` — ${w.organization}` : ''} (${w.position})`)));
            details.append(ul);
            box.append(details);
        }
        const note = stageNode('p', 'From the official witness list. Testimony content is not recorded.', 'stage-small');
        if (typeof p.source === 'string' && p.source.startsWith(LEGIS_FTP)) {
            const a = stageNode('a', 'Official witness list', 'text-link');
            a.href = p.source; a.target = '_blank'; a.rel = 'noopener noreferrer';
            note.append(' ', a);
        }
        box.append(note);
        section.append(box);
    }
    return section;
}

export function validFiscal(data, billId, current) {
    if (!data || typeof data !== 'object' || data.format !== 'texas-bill-luna-fiscal-v1' || data.bill_id !== billId) return false;
    if (!current || typeof current.text_version !== 'string' || typeof current.text_sha256 !== 'string') return false;
    return data.text_version === current.text_version && data.text_sha256 === current.text_sha256;
}

const DOC_LABELS = {fiscal_note: 'Fiscal note (text)', analysis: 'Bill analysis (text)'};

export function renderFiscal(data, billId) {
    const section = stageNode('section', undefined, 'drawer-section stage-section stage-fiscal');
    section.append(stageNode('h3', 'Fiscal note check'));
    section.append(stageNode('p', "Luna's comparison of the fiscal note and bill analysis with the bill text. It is not an official finding."));
    const summary = data.summary && typeof data.summary.text === 'string' && data.summary.text ? data.summary.text : '';
    if (data.no_fiscal_implication === true || summary) {
        const box = stageNode('div', undefined, 'evidence-card');
        if (data.no_fiscal_implication === true) box.append(stageNode('p', 'The fiscal note reports no significant fiscal implication.'));
        else {
            box.append(stageNode('p', summary));
            const sq = quotesBlock('Quoted text', data.summary.quotes);
            if (sq) box.append(sq);
        }
        section.append(box);
    }
    const agencies = (Array.isArray(data.agencies) ? data.agencies : []).filter(a => a && typeof a.name === 'string');
    if (agencies.length) {
        section.append(stageNode('h4', 'Agencies'));
        const ul = stageNode('ul', undefined, 'stage-list');
        for (const a of agencies) {
            const li = stageNode('li');
            li.append(stageNode('strong', a.name));
            if (typeof a.fiscal_effect === 'string' && a.fiscal_effect) li.append(' · ' + a.fiscal_effect);
            if (a.in_review === false) li.append(' ', stageNode('small', "not in Luna's review", 'stage-small'));
            const q = quotesBlock('Quoted text', a.quotes);
            if (q) li.append(q);
            ul.append(li);
        }
        section.append(ul);
    }
    const dis = (Array.isArray(data.disagreements) ? data.disagreements : []).filter(d => d && typeof d.claim === 'string');
    if (dis.length) {
        const ul = stageNode('ul', undefined, 'stage-list');
        for (const d of dis) {
            const li = stageNode('li');
            li.append(stageNode('strong', 'Fiscal note differs: '), d.claim);
            if (typeof d.note === 'string' && d.note) li.append(stageNode('p', d.note));
            const q = quotesBlock('Quoted text', d.quotes);
            if (q) li.append(q);
            ul.append(li);
        }
        section.append(ul);
    }
    const docs = (Array.isArray(data.documents) ? data.documents : []).filter(d => d && DOC_LABELS[d.type] && /^[A-Za-z0-9]{1,8}$/.test(String(d.code)));
    if (docs.length && /^[A-Z]{2,3}\d{1,5}$/.test(billId)) {
        const p = stageNode('p', undefined, 'stage-small');
        docs.forEach((d, i) => {
            const a = stageNode('a', DOC_LABELS[d.type], 'text-link');
            a.href = `./live/history/${billId}/${d.type}-${d.code}.md`; a.target = '_blank'; a.rel = 'noopener noreferrer';
            if (i) p.append(' · ');
            p.append(a);
        });
        section.append(p);
    }
    return section;
}

// ---- Statutes: the sections of Texas law each bill changes (live/statutes, built by scripts/build_feeds.py) ----
// Kept in this module because the deployer publishes a fixed list of src/ files.

export const STATUTE_KEY = /^([A-Z]{2}) (\d+[A-Z]?(?:\.\d+[A-Z]?)+)$/;
export const STATUTE_KINDS = {m: 'amends', n: 'adds a new section', r: 'repeals'};
const isMap = o => o && typeof o === 'object' && !Array.isArray(o);

export const statuteFile = key => STATUTE_KEY.test(key) && key.length <= 20 ? `${key.replace(' ', '-')}.json` : null;
export function statuteLabel(key, codes) {
    const m = STATUTE_KEY.exec(key || '');
    if (!m) return String(key || '');
    return `${codes?.[m[1]] || m[1]} ${m[1] === 'CR' ? 'Art.' : '§'} ${m[2]}`;
}
// Checked against statutes.capitol.texas.gov for every code the index uses.
export function officialStatuteUrl(key) {
    const m = STATUTE_KEY.exec(key || '');
    if (!m) return '';
    return `https://statutes.capitol.texas.gov/?tab=1&code=${m[1]}&chapter=${m[1]}.${m[2].split('.')[0]}&artSec=${m[2]}`;
}
export const validStatuteIndex = x => x?.format === 'texas-bill-statutes-v1' && isMap(x.sections) && isMap(x.bills) && isMap(x.codes);
export const validStatuteSection = (x, key) => x?.format === 'texas-bill-statute-section-v1' && x.key === key && Array.isArray(x.entries);

// bill id -> [{key, kind, others}] from the index's section -> bills map.
export function statutesByBill(index) {
    const out = new Map();
    for (const [key, s] of Object.entries(index?.sections || {})) {
        if (!STATUTE_KEY.test(key) || !Array.isArray(s?.b)) continue;
        for (const pair of s.b) {
            if (!Array.isArray(pair) || typeof pair[0] !== 'string' || !STATUTE_KINDS[pair[1]]) continue;
            if (!out.has(pair[0])) out.set(pair[0], []);
            out.get(pair[0]).push({key, kind: pair[1], others: s.b.length - 1});
        }
    }
    return out;
}

// "48.160", "§ 48.160", "Penal Code 46.06", "ED 48.160", "CCP art. 46.04" -> {code (or null for any code), sec}.
export function parseStatuteQuery(query, codes) {
    const text = String(query || '').trim().replace(/\s+/g, ' ');
    const m = /^(.*?)[\s,]*(?:§+\s*|sec(?:tion)?\.?\s+|art(?:icle)?\.?\s+)?(\d+[a-z]?(?:\.\d+[a-z]?)+)$/i.exec(text);
    if (!m) return null;
    const sec = m[2].toUpperCase(), name = m[1].trim().replace(/[,§]+$/, '').trim().toLowerCase();
    if (!name) return {code: null, sec};
    for (const [abbr, full] of Object.entries(codes || {})) {
        const f = full.toLowerCase();
        if (name === abbr.toLowerCase() || name === f || name === f.replace(/ code$/, '') || name === f.replace(/^code of /, '')
            || (abbr === 'CR' && /^(ccp|c\.c\.p\.)$/.test(name))) return {code: abbr, sec};
    }
    return null;
}
// Section keys in the index that a parsed query names.
export function statuteKeysFor(index, parsed) {
    if (!parsed || !index?.sections) return [];
    return Object.keys(index.sections).filter(k => {
        const m = STATUTE_KEY.exec(k);
        return m && m[2] === parsed.sec && (!parsed.code || parsed.code === m[1]);
    });
}

// One quoted paragraph as current law (unmarked + struck words) and as proposed (unmarked + added words). The bill
// wraps struck words in brackets outside the del tags ("\[<del>old</del>\]"); those brackets belong to neither.
export function lawParagraph(line) {
    const segments = parseParagraph(line, 1).segments.map(s => ({...s}));
    segments.forEach((s, i) => {
        if (s.mark !== 'del') return;
        const before = segments[i - 1], after = segments[i + 1];
        if (before && !before.mark && before.text.endsWith('[')) before.text = before.text.slice(0, -1);
        if (after && !after.mark && after.text.startsWith(']')) after.text = after.text.slice(1);
    });
    const join = keep => segments.filter(s => !s.mark || s.mark === keep).map(s => s.text).join('').replace(/\s+/g, ' ').trim();
    return {current: join('del'), proposed: join('ins')};
}

const SECTION_HEAD = /^((?:Sec|Art)\. \d+[A-Z]?(?:\.\d+[A-Z]?)+\.\s+[^a-z]*?\.)(?:\s+|$)/;
const SUB_LABEL = /^\(([a-z]{1,3}(?:-\d+[a-z]?)?)\)\s/;

// Paragraphs of one bill's entry -> ordered [{label, text}] for one version. "head" is "Sec. N. HEADING."; "" is
// body text before any lettered subsection; numbered and capital-lettered paragraphs stay with their subsection.
export function lawUnits(paragraphs, which) {
    const units = [];
    let current = null;
    const push = (label, text) => {
        if (!text) return;
        if (current && current.label === label) current.text += `\n${text}`;
        else { current = {label, text}; units.push(current); }
    };
    for (const line of paragraphs || []) {
        let text;
        try { text = lawParagraph(line)[which]; } catch { continue; }
        const head = SECTION_HEAD.exec(text);
        if (head) { push('head', head[1]); text = text.slice(head[0].length); }
        const sub = SUB_LABEL.exec(text);
        push(sub ? sub[1] : current && current.label !== 'head' ? current.label : '', text.trim());
    }
    return units.filter(u => u.text.trim());
}

const labelRank = label => {
    if (label === 'head') return [-2, 0, 0];
    if (label === '') return [-1, 0, 0];
    const m = /^([a-z]+)(?:-(\d+)([a-z]?))?$/.exec(label) || [];
    const letters = m[1] || '';
    return [letters.length * 100 + (letters.charCodeAt(0) - 96), Number(m[2] || 0), (m[3] || '').charCodeAt(0) || 0];
};
const byLabel = (a, b) => {
    const x = labelRank(a), y = labelRank(b);
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
};

// Words and punctuation as tokens; `space` records whether whitespace came before, so text rebuilds exactly and
// "Beta." vs "Beta changed." differs only in "changed". A newline (between paragraphs) is kept as its own token.
export function lawTokens(text) {
    const out = [];
    for (const m of String(text).matchAll(/(\s*)([^\s.,;:!?()[\]"]+|[.,;:!?()[\]"])/g)) {
        if (m[1].includes('\n')) out.push({t: '\n', space: false});
        out.push({t: m[2], space: m[1].length > 0 && !m[1].includes('\n')});
    }
    return out;
}

// Token-level differences: [{t, space, changed}] for each side. Long, very different texts are marked changed whole.
export function wordDiff(a, b, limit = 2_500_000) {
    const x = lawTokens(a), y = lawTokens(b);
    const all = list => list.map(w => ({...w, changed: w.t !== '\n'}));
    if (x.length * y.length > limit) return {left: all(x), right: all(y), approximate: true};
    const n = x.length, m = y.length, table = new Uint32Array((n + 1) * (m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
        table[i * (m + 1) + j] = x[i].t === y[j].t ? table[(i + 1) * (m + 1) + j + 1] + 1 : Math.max(table[(i + 1) * (m + 1) + j], table[i * (m + 1) + j + 1]);
    const left = [], right = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
        if (x[i].t === y[j].t) { left.push({...x[i++], changed: false}); right.push({...y[j++], changed: false}); }
        else if (table[(i + 1) * (m + 1) + j] >= table[i * (m + 1) + j + 1]) left.push({...x[i++], changed: true});
        else right.push({...y[j++], changed: true});
    }
    while (i < n) left.push({...x[i++], changed: true});
    while (j < m) right.push({...y[j++], changed: true});
    return {left, right, approximate: false};
}

// A side of a comparison: {units, partial, name}. partial = it quotes only some subsections, so a missing one is
// "not changed by it" rather than "not in it".
export function compareLaw(left, right) {
    const l = new Map(left.units.map(u => [u.label, u.text])), r = new Map(right.units.map(u => [u.label, u.text]));
    const labels = [...new Set([...l.keys(), ...r.keys()])].sort(byLabel);
    const missing = (side, other) => side.partial ? `Not changed by ${side.name}` : `Not in ${side.name}`;
    return labels.map(label => {
        if (l.has(label) && r.has(label)) {
            const d = wordDiff(l.get(label), r.get(label));
            return {label, left: d.left, right: d.right, approximate: d.approximate, same: d.left.every(w => !w.changed) && d.right.every(w => !w.changed)};
        }
        const [has, side] = l.has(label) ? ['left', right] : ['right', left];
        // Missing from a whole-section quote: the words are gone on that side. Missing from a partial quote: unchanged.
        const marked = lawTokens(l.get(label) ?? r.get(label)).map(w => ({...w, changed: !side.partial && w.t !== '\n'}));
        return {label, left: has === 'left' ? marked : null, right: has === 'right' ? marked : null,
            leftNote: has === 'right' ? missing(left) : '', rightNote: has === 'left' ? missing(right) : ''};
    });
}

// Current law as the bills quote it: for each subsection, the first amending entry that quotes it (whole-section
// quotes first). Returns {units, sources: [bill ids], partial}.
export function currentLaw(entries) {
    const amending = (entries || []).filter(e => e.kind === 'amend').sort((a, b) => Number(a.partial) - Number(b.partial));
    const units = new Map(), sources = new Set();
    for (const e of amending) {
        for (const u of lawUnits(e.paragraphs, 'current')) {
            if (!units.has(u.label)) { units.set(u.label, u.text); sources.add(e.bill); }
        }
    }
    const partial = !amending.some(e => !e.partial);
    return {units: [...units].map(([label, text]) => ({label, text})).sort((a, b) => byLabel(a.label, b.label)), sources: [...sources], partial};
}

// Entries with the same kind and the same proposed wording (companions, copies) shown as one version.
export function groupStatuteEntries(entries, broad = () => false) {
    const groups = new Map();
    for (const e of entries || []) {
        const units = lawUnits(e.paragraphs, 'proposed');
        const signature = `${e.kind}|${units.map(u => `${u.label}:${u.text}`).join('\n')}`;
        const key = units.length ? signature : `${e.kind}|${e.bill}`;
        if (!groups.has(key)) groups.set(key, {kind: e.kind, entries: [], units, partial: Boolean(e.partial)});
        groups.get(key).entries.push(e);
    }
    const order = {amend: 0, add: 1, repeal: 2};
    return [...groups.values()].map(g => ({...g, broad: g.entries.every(e => broad(e.bill))}))
        .sort((a, b) => order[a.kind] - order[b.kind] || Number(a.broad) - Number(b.broad) || b.entries.length - a.entries.length);
}
