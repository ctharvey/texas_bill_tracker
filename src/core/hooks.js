// Page-level actions features call back into (renderContent, renderOverview, showDrawer, toast), so a feature never
// imports app.js. app.js registers them at the start of init(), before anything renders.
export const hooks = {};
export function registerHooks(fns){Object.assign(hooks,fns)}
