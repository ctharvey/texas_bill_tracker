// Loading a local bill file (JSON or CSV) into the explorer for this session only; a failed draw restores the old list.
import {parseCsv} from './csv.js';
import {normalizeBill, attachMembers} from '../../taxonomy.js';
import {state} from '../../core/state.js';
import {switchFilters, goTo} from '../../core/location.js';
import {toast} from '../../core/dom.js';
import {setView} from '../../core/router.js';

export async function importFile(file){
  try{
    if(file.size>15*1024*1024)throw Error('Select a file smaller than 15 MB');
    const contents=await file.text();const data=file.name.toLowerCase().endsWith('.csv')?parseCsv(contents):JSON.parse(contents);
    const rows=Array.isArray(data)?data:data.bills;
    if(!Array.isArray(rows))throw Error('Expected an array of bills or an object with a bills array');
    const profiles=!Array.isArray(data)&&data.author_profiles&&typeof data.author_profiles==='object'?data.author_profiles:null;
    const valid=rows.filter(r=>r&&typeof r==='object').map(raw=>normalizeBill(raw,profiles)).filter(Boolean).map(b=>attachMembers(b,state.roster));
    if(!valid.length)throw Error('No valid Texas bill numbers found');
    const previous={bills:state.bills,meta:state.meta,topic:state.topic,area:state.area,agency:state.agency,chamber:state.chamber,party:state.party,stage:state.stage,action:state.action,outlook:state.outlook,query:state.query,visibleCount:state.visibleCount,view:state.view};
    try{
      state.bills=valid;state.meta={session:'90R',data_mode:'local import',source_file:file.name,generated_at:new Date().toISOString(),coverage_note:`Local file: ${file.name}. Imported rows are visible only during this session.`};
      switchFilters('all');Object.assign(state,{topic:'',area:'',agency:'',chamber:'',party:'',stage:'',action:'',outlook:'',query:'',visibleCount:30});setView('all');
    }catch(renderError){Object.assign(state,previous);setView(previous.view);throw renderError}
    goTo('all');toast(`Imported ${valid.length} bills`);
  }catch(err){toast(`Import failed: ${err.message}`)}
}
