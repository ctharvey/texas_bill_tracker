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
