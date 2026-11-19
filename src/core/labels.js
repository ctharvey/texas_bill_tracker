// Names and days that many views share: the explorer's sort labels, agency and reader-area names (Luna's file adds
// agencies), a bill's agencies without the scope placeholder, and today's date in Texas.
import {AGENCY_NAME, SCOPE_AGENCY_ID, chicagoDate} from '../taxonomy.js';
import {state} from './state.js';
import {AREA_BY_ID} from '../features/areas/model.js';

export const SORTS={newest:'Newest filed',latest:'Latest action',oldest:'Oldest last action',actionstage:'Last action stage',number:'Bill number',agencies:'Most agencies',hearing:'Hearing progress',influence:'Author influence'};
export const agencyName = id => AGENCY_NAME[id]||state.luna?.agencies?.[id]||id;
export const areaName = id => AREA_BY_ID.get(id)?.name||id;
export const realAgencies = b => b.agencies.filter(a=>a.id!==SCOPE_AGENCY_ID);
export const todayDay=()=>chicagoDate(new Date());
