// View registry: each view's page heading and how its content renders. A feature registers its own views; a view
// no one registered renders as the fallback view (the data page), as the old renderContent chain did.
const views = new Map();
let fallback = null;

export function registerView(name, {heading, render, after}){
  if(views.has(name))throw Error(`View ${name} registered twice`);
  views.set(name, {heading, render, after});
}
export function setFallbackView(name){fallback=name}
// [title html, subtitle text], or undefined for a view no one registered.
export const viewHeading = name => views.get(name)?.heading;
export function renderView(name, el){
  const view=views.get(name)||views.get(fallback);
  el.innerHTML=view.render();
  view.after?.();
}
// The app's full redraw of the current view, for features that redraw after async work. app.js sets it before boot.
let redraw = () => {};
export function setRenderContent(fn){redraw=fn}
export const renderContent = () => redraw();
// The explorer's results redraw (keeping focus) and the address and remembered-filters save; app.js sets both before boot.
let redrawResults = () => {}, persist = () => false;
export function setExplorerHooks({renderResults, persistState}){redrawResults=renderResults;persist=persistState}
export const renderResults = () => redrawResults();
export const persistState = push => persist(push);
// The page chrome and view switch the saved-lists and sync code redraws after a change; app.js sets them before boot.
let hooks = {renderOverview(){}, refreshHome(){}, renderMoveBanner(){}, setView(){}};
export function setSyncHooks(fns){hooks=fns}
export const renderOverview = () => hooks.renderOverview();
export const refreshHome = () => hooks.refreshHome();
export const renderMoveBanner = () => hooks.renderMoveBanner();
export const setView = (...args) => hooks.setView(...args);
