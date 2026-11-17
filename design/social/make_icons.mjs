// Draw public/icon.png, public/apple-touch-icon.png and public/favicon.ico from the warbler logo in design/brand/.
// Run by hand when the logo changes (after npm install): node design/social/make_icons.mjs
// warbler.svg is the logo; warbler-small.svg is the same bird simplified for 16-48 px.
import {readFileSync, writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const NAVY = '#14243a'; // --nav-bg of the default palette, as on the social card.
const require = createRequire(import.meta.url);
const {initWasm, Resvg} = await import('@resvg/resvg-wasm');
await initWasm(readFileSync(require.resolve('@resvg/resvg-wasm/index_bg.wasm')));

const logo = readFileSync(join(ROOT, 'design/brand/warbler.svg'), 'utf8');
const small = readFileSync(join(ROOT, 'design/brand/warbler-small.svg'), 'utf8');

function png(svg, size) {
  const resvg = new Resvg(svg, {fitTo: {mode: 'width', value: size}});
  const data = Buffer.from(resvg.render().asPng());
  resvg.free();
  return data;
}

// An .ico of PNG images, one per size (every current browser reads PNG entries).
function ico(images) {
  const head = Buffer.alloc(6 + 16 * images.length);
  head.writeUInt16LE(1, 2);
  head.writeUInt16LE(images.length, 4);
  let offset = head.length;
  images.forEach(({size, data}, i) => {
    const at = 6 + 16 * i;
    head.writeUInt8(size, at);
    head.writeUInt8(size, at + 1);
    head.writeUInt16LE(1, at + 4);
    head.writeUInt16LE(32, at + 6);
    head.writeUInt32LE(data.length, at + 8);
    head.writeUInt32LE(offset, at + 12);
    offset += data.length;
  });
  return Buffer.concat([head, ...images.map(image => image.data)]);
}

// iOS rounds the corners itself and shows transparency as black, so the touch icon is a full-bleed navy square.
const inner = logo.replace(/^\s*<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '');
const touch = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect width="256" height="256" fill="${NAVY}"/>`
  + `<g transform="translate(128 128) scale(.84) translate(-128 -128)">${inner}</g></svg>`;

const out = join(ROOT, 'public');
writeFileSync(join(out, 'icon.png'), png(logo, 192));
writeFileSync(join(out, 'apple-touch-icon.png'), png(touch, 180));
writeFileSync(join(out, 'favicon.ico'), ico([16, 32, 48].map(size => ({size, data: png(small, size)}))));
console.log('wrote public/icon.png, public/apple-touch-icon.png, public/favicon.ico');
