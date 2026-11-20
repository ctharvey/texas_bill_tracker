// Writes public/routes.json from the app's route table (src/core/routes.js), published at /routes.json for the
// gateway's route test and the E2E server. Run after changing a route: node scripts/routes_json.mjs
// tests/routes.test.mjs fails while the file and the table disagree.
import {writeFileSync} from 'node:fs';
import {routeList} from '../src/core/routes.js';

writeFileSync(new URL('../public/routes.json', import.meta.url), JSON.stringify(routeList(), null, 1) + '\n');
