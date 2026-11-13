// Page clicks are resolved in one fixed order: the check order of the original handleClick. A feature registers its
// handler under one of these names, so a click resolves the same way whatever order modules load in.
export const CLICK_ORDER = ['agency-sort', 'agency-option', 'agency-combobox', 'agency-dismiss', 'nav', 'open-bill', 'copy-ai',
  'near-locate', 'near-forget', 'near-change', 'near-county-use', 'near-numbers-use', 'near-more', 'follow',
  'save-search', 'search-open', 'search-rename', 'search-delete', 'follow-more', 'law-compare', 'law-show',
  'member-more', 'copy-page-ai', 'today-topic', 'today-more', 'today-topics-toggle', 'save-tools', 'watch-group',
  'watch', 'search-example', 'topic', 'agency-pick', 'clear-filter', 'clear-filters', 'watch-filter', 'load-more', 'export-csv', 'import-trigger',
  'nav-more', 'bill-back', 'preview-close', 'preview-step', 'bill-jump', 'card'];

const handlers = new Map();

// handler(event) returns true when the click was its own; the handlers after it then never see the click.
export function onClick(name, handler){
  if(!CLICK_ORDER.includes(name))throw Error(`Unknown click handler ${name}`);
  if(handlers.has(name))throw Error(`Click handler ${name} registered twice`);
  handlers.set(name, handler);
}
// The common case: the click is inside `selector`; fn gets that element and the event.
export const clickOn = (name, selector, fn) => onClick(name, e => {
  const el=e.target.closest(selector);
  if(!el)return false;
  fn(el, e);
  return true;
});
export function dispatchClick(e){
  for(const name of CLICK_ORDER){const handler=handlers.get(name);if(handler&&handler(e))return}
}
