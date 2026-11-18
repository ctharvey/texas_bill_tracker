// Bill text: the Markdown files in live/text (written by scripts/sync_ftp.py) parsed into paragraphs of
// inserted, deleted and plain runs, and the checks a Luna highlights file must pass before it is drawn.
const MAX_BYTES = 8 * 1024 * 1024;
const TAGS = {'<ins>': ['open', 'ins'], '</ins>': ['close', 'ins'], '<del>': ['open', 'del'], '</del>': ['close', 'del']};
const TAG_RE = /^<\/?(?:ins|del)>/;
export const KINDS = ['agency', 'effect', 'topic', 'group', 'location', 'summary', 'scope'];
export const CHIPS = [['agency', 'Agencies'], ['effect', 'Effects'], ['topic', 'Topics'], ['group', 'Groups'],
    ['location', 'Locations'], ['summary', 'Summary']];
export const chipOf = kind => kind === 'scope' ? 'agency' : kind; // the all-agencies scope marker toggles with Agencies

export function parseParagraph(line, index) {
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
