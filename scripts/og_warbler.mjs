// The warbler mark for share cards: a copy of design/brand/warbler.svg (tests/og_card.test.mjs checks they match).
// It lives under scripts/ because texas-bill-og.service gets only scripts/ and the package files, not design/.
export const WARBLER_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-label="Texas Bill Atlas warbler">
  <defs>
    <!-- one side of the face: golden cheek, eye line from the bill through the eye, small ringed eye -->
    <!-- eye line is cut out of the cheek so the head's own black shows through: no black-on-black edges -->
    <mask id="eyeline" maskUnits="userSpaceOnUse" x="0" y="0" width="256" height="256">
      <rect width="256" height="256" fill="#FFFFFF"/>
      <path d="M124 130 C104 130 92 129 82 129 C70 129 60 135 50 144 C62 140 72 139 82 139 C92 139 104 138 124 138 Z" fill="#000000"/>
    </mask>
    <g id="side">
      <g mask="url(#eyeline)">
        <path transform="rotate(-12 92 140)" d="M100 98 C86 92 66 98 58 116 C50 132 44 158 54 176 C64 194 94 198 108 182 C118 170 116 150 112 132 C110 116 106 102 100 98 Z" fill="#F5B517"/>
      </g>
      <circle cx="82" cy="134" r="12.5" fill="#FFFFFF" stroke="#141414" stroke-width="3"/>
      <circle cx="84.5" cy="135" r="7.5" fill="#141414"/>
      <circle cx="87" cy="131.5" r="2.8" fill="#FFFFFF"/>
    </g>
  </defs>
  <g transform="translate(128 128) scale(1.12) translate(-128 -146)">
    <!-- cream outline for dark backgrounds -->
    <circle cx="128" cy="146" r="90" fill="#F7F3EA" stroke="#F7F3EA" stroke-width="12"/>
    <circle cx="128" cy="146" r="90" fill="#141414"/>
    <use href="#side" transform="translate(-3 0)"/>
    <use href="#side" transform="matrix(-1 0 0 1 259 0)"/>
    <!-- bill -->
    <path d="M119.5 157 L136.5 157 L128 170 Z" fill="#8E8E8E" stroke="#8E8E8E" stroke-width="4" stroke-linejoin="round"/>
  </g>
</svg>
`;
