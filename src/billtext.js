// Re-exports for tests/billtext.test.mjs; the code lives in src/features/billtext/.
export {parseBillMarkdown, paragraphSegments, validHighlights, sha256Hex} from './features/billtext/model.js';
export {renderBillText} from './features/billtext/view.js';
