// Drawing bill text: renderBillText fills a root with the parsed paragraphs and Luna's highlight chips;
// billTextSection is the bill page's "Bill text" section, which fetches a version and its highlights on demand.
import {state} from '../../core/state.js';
import {timeoutSignal, httpError, discard} from '../../core/net.js';
import {officialUrl} from '../../taxonomy.js';
import {KINDS, CHIPS, chipOf, paragraphSegments, parseBillMarkdown, validHighlights, sha256Hex} from './model.js';

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
            // A highlight acts as a button (it opens the explanation) but stays a <mark>, so the text can still be selected.
            m.tabIndex = 0; m.setAttribute('role', 'button');
            m.addEventListener('click', () => explain(seg.ids));
            m.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); explain(seg.ids); } });
            marks.push(m);
            seg.ids.forEach(id => { if (!firstMark.has(id)) firstMark.set(id, m); });
            target.append(m);
        }
        body.append(el);
    });
    root.append(body);
}

export function billTextSection(b){
  const section=document.createElement('section');section.className='drawer-section bill-text-section';
  const heading=document.createElement('h3');heading.textContent='Bill text';
  const intro=document.createElement('p');intro.textContent='Read the filed text with additions underlined and deletions struck through. Luna highlights show where its tags come from.';
  const button=document.createElement('button');button.className='outline-button';button.type='button';button.textContent='Show bill text';
  const picker=document.createElement('div');picker.className='bt-versions';
  const area=document.createElement('div');area.setAttribute('aria-live','polite');
  const official=document.createElement('p');official.hidden=true;
  const link=document.createElement('a');link.className='text-link';link.href=/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/.test(b.id)?`https://capitol.texas.gov/BillLookup/Text.aspx?LegSess=90R&Bill=${b.id}`:officialUrl(b);link.target='_blank';link.rel='noopener noreferrer';link.textContent='Read the official text on Texas Legislature Online ↗';
  official.append(link);
  section.append(heading,intro,button,picker,area,official);
  const idOk=/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/.test(b.id);
  const fetchText=async url=>{const r=await fetch(url,{cache:'no-cache',signal:timeoutSignal(20000)});if(r.status===404)return discard(r);if(!r.ok)throw httpError(r);return r};
  let selected=null,versions=[],select=null,highlightsPromise=null;
  const highlightsOnce=()=>highlightsPromise||(highlightsPromise=(async()=>{try{const hr=await fetchText(`./live/luna/highlights/${b.id}.json`);return hr?await hr.json():null}catch{return null}})());
  const loadVersion=async(index,version)=>{
    selected=version.code;area.textContent='Loading bill text…';
    const stale=()=>state.openBill!==b.id||selected!==version.code;
    try{
      if(!/^[A-Z0-9]{1,3}$/.test(version.code))throw Error('Unexpected version code');
      const textResponse=await fetchText(`./live/text/${b.id}/${version.code}.md`);
      if(!textResponse)throw Error('This version is not available yet');
      const raw=await textResponse.text();
      let highlights=null,note,other=null;
      const candidate=await highlightsOnce();
      if(candidate&&typeof candidate.text_version==='string'){
        if(candidate.text_version===version.code){
          if(validHighlights(candidate,b.id,version.code,await sha256Hex(raw)))highlights=candidate;
          else note='Luna highlights do not match this version of the text.';
        }else{
          const idx=versions.findIndex(v=>v.code===candidate.text_version);
          if(idx>=0){other={idx,name:versions[idx].name||versions[idx].code};note=' '}
        }
      }
      const parsed=parseBillMarkdown(raw);
      if(stale())return;
      renderBillText(area,parsed,highlights,{highlightsNote:note,idPrefix:`bt-${b.id}`});
      if(other){
        const line=document.createElement('p');line.className='bt-note';
        const go=document.createElement('button');go.type='button';go.className='outline-button';go.textContent=`Luna's highlights are on the ${other.name} text`;
        go.addEventListener('click',()=>{if(select){select.value=String(other.idx)}loadVersion(other.idx,versions[other.idx])});
        line.append(go);area.prepend(line);
      }
    }catch(error){
      if(stale())return;
      area.textContent='The bill text could not be shown: '+error.message;
    }
  };
  button.addEventListener('click',async()=>{
    button.disabled=true;official.hidden=false;area.textContent='Loading bill text…';
    try{
      if(!idOk)throw Error('Unexpected bill id');
      const response=await fetchText(`./live/text/${b.id}/index.json`);
      if(state.openBill!==b.id)return;
      if(!response){
        area.replaceChildren(document.createTextNode('The bill text is not on this site yet; it is added within a few hours of filing. Read it on '),link,document.createTextNode('.'));
        official.hidden=true;button.hidden=true;return;
      }
      const index=await response.json();
      versions=Array.isArray(index?.versions)?index.versions.filter(v=>v&&/^[A-Z0-9]{1,3}$/.test(v.code)):[];
      if(index?.format!=='texas-bill-text-index-v1'||index.bill_id!==b.id||!versions.length)throw Error('The text index is not valid');
      if(state.openBill!==b.id)return;
      button.hidden=true;
      select=document.createElement('select');select.setAttribute('aria-label','Bill text version');
      versions.forEach((v,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=v.name?`${v.name} (${v.code})`:v.code;select.append(o)});
      select.value=String(versions.length-1);
      select.addEventListener('change',()=>loadVersion(Number(select.value),versions[Number(select.value)]));
      picker.append(select);
      await loadVersion(versions.length-1,versions[versions.length-1]);
    }catch(error){
      button.disabled=false;area.textContent='The bill text could not be loaded: '+error.message;
    }
  });
  return section;
}
