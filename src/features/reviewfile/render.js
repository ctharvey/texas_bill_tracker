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
