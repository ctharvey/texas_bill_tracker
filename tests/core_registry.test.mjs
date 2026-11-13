import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {CLICK_ORDER, onClick, clickOn, dispatchClick} from '../src/core/dispatch.js';
import {registerView, setFallbackView, viewHeading, renderView} from '../src/core/router.js';

const app = readFileSync(new URL('../src/app.js', import.meta.url), 'utf8');
const target = matches => ({closest: selector => matches.includes(selector) ? {selector} : null});

// The registries are module singletons, so the dispatch tests share one set of handlers.
const seen = [];
onClick('agency-dismiss', () => {seen.push('agency-dismiss'); return false});
clickOn('watch', '[data-watch]', el => seen.push('watch:' + el.selector));
clickOn('topic', '[data-topic]', () => seen.push('topic'));
clickOn('nav', '[data-view]', () => seen.push('nav'));

test('a click runs handlers in CLICK_ORDER, not registration order, and stops at the first that claims it', () => {
  seen.length = 0;
  dispatchClick({target: target(['[data-topic]', '[data-watch]', '[data-view]'])});
  assert.deepEqual(seen, ['agency-dismiss', 'nav']);  // nav precedes watch and topic in the original handleClick
  seen.length = 0;
  dispatchClick({target: target(['[data-topic]', '[data-watch]'])});
  assert.deepEqual(seen, ['agency-dismiss', 'watch:[data-watch]']);
  seen.length = 0;
  dispatchClick({target: target([])});
  assert.deepEqual(seen, ['agency-dismiss']);  // a handler returning false lets the click go on
});

test('handler names are fixed and registered once', () => {
  assert.throws(() => onClick('not-a-handler', () => true), /Unknown click handler/);
  assert.throws(() => onClick('watch', () => true), /registered twice/);
});

test('app.js registers every click handler exactly once, and nothing else', () => {
  const names = [...app.matchAll(/\b(?:onClick|clickOn)\('([\w-]+)'/g)].map(m => m[1]);
  assert.deepEqual([...names].sort(), [...CLICK_ORDER].sort());
  assert.deepEqual(names, CLICK_ORDER);  // written in dispatch order, so the source reads like the old handleClick
  assert.doesNotMatch(app, /function handleClick/);
});

test('app.js registers the twelve views, with the data page as the fallback', () => {
  const names = [...app.matchAll(/registerView\('(\w+)'/g)].map(m => m[1]);
  assert.deepEqual(names, ['all', 'watchlist', 'following', 'today', 'local', 'member', 'statute', 'agencies', 'review',
    'method', 'saving', 'data']);
  assert.match(app, /setFallbackView\('data'\)/);
});

test('a view renders into the element and runs its after-render step; an unknown view renders the fallback', () => {
  const calls = [];
  registerView('t-list', {heading: ['T', 'sub'], render: () => '<list>', after: () => calls.push('after')});
  registerView('t-data', {heading: ['D', 'sub'], render: () => '<data>'});
  setFallbackView('t-data');
  const el = {innerHTML: ''};
  renderView('t-list', el);
  assert.deepEqual([el.innerHTML, calls], ['<list>', ['after']]);
  renderView('t-nowhere', el);
  assert.equal(el.innerHTML, '<data>');
  assert.deepEqual(viewHeading('t-list'), ['T', 'sub']);
  assert.equal(viewHeading('t-nowhere'), undefined);
  assert.throws(() => registerView('t-list', {heading: [], render: () => ''}), /registered twice/);
});
