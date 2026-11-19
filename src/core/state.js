// The page's one state object. Features import it from here, never from app.js.
export const state = {view:'all',bills:[],watch:new Set(),query:'',topic:'',agency:'',chamber:'',party:'',stage:'',action:'',outlook:'',sort:'newest',onlyWatch:false,companion:false,visibleCount:30,meta:null,luna:null,related:null,audit:null,roster:null,reviewStatus:null,sharedList:null,sharedMode:null,sharedSyncKey:null,openBill:null,todayTopic:'',todayLimit:100,todayAllTopics:false,near:null,nearGeo:null,nearPick:null,nearBusy:'',nearError:'',nearShow:{members:5,area:5},memberCode:null,memberShow:{},geoTables:null,statutes:null,statutesFailed:false,statuteKey:null,statuteCompare:null,statuteShow:'both',brackets:null,
  follow:[],followShow:30,searches:[],renamingSearch:null};
// Values app.js and features both read and set, kept apart from the state object so its keys stay the page's state.
// restoredFilters: the explorer's filters as restored from the last visit; the chips say so until any of them changes.
// syncAvailable: whether this site's sync links work; null until the first check.
// moveStatus: Old site: null, 'moving', 'moved' or 'failed:<reason>'. New site: the arrival result.
export const runtime = {restoredFilters:null,syncAvailable:null,moveStatus:null};
