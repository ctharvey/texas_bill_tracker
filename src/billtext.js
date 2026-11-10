// The bill text code lives in review.js: the installed static deployer ships a fixed list of src files
// (scripts/deploy_static.py FILES), and a module missing from it breaks every page that imports it.
export {parseBillMarkdown, paragraphSegments, validHighlights, sha256Hex, renderBillText} from './review.js';
