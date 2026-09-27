// Hand-drawn city silhouettes for the weather widget background (no external images).
// viewBox is 400 x 120; the ground is the bottom edge.

export function CitySkyline({ city }: { city: string }) {
  return (
    <svg className="skyline" viewBox="0 0 400 120" preserveAspectRatio="xMidYMax slice" aria-hidden>
      {city === 'Bucharest' ? <Bucharest /> : <Aarhus />}
    </svg>
  )
}

function Aarhus() {
  return (
    <>
      <defs>
        <linearGradient id="aros-rainbow" x1="0" x2="1">
          <stop offset="0" stopColor="#ff4d4d" />
          <stop offset="0.2" stopColor="#ffa94d" />
          <stop offset="0.4" stopColor="#ffe066" />
          <stop offset="0.6" stopColor="#69db7c" />
          <stop offset="0.8" stopColor="#4dabf7" />
          <stop offset="1" stopColor="#b197fc" />
        </linearGradient>
      </defs>
      <g className="skyline-far">
        {/* low harbour-front houses */}
        <path d="M0 120 V104 H40 V98 H70 V106 H400 V120 Z" />
      </g>
      <g className="skyline-near">
        {/* Isbjerget ("The Iceberg") */}
        <path d="M0 120 V96 L16 74 L28 90 L44 62 L60 88 L76 68 L94 120 Z" />
        {/* Dokk1 library */}
        <path d="M100 120 V102 L168 93 L204 101 V120 Z" />
        {/* Aarhus Cathedral */}
        <path d="M212 120 V88 H228 V58 L235 24 L242 58 V88 H258 V120 Z" />
        {/* ARoS art museum */}
        <path d="M276 120 V72 H352 V120 Z" />
        {/* houses */}
        <path d="M360 120 V100 L370 92 L380 100 V120 Z M382 120 V104 L391 97 L400 104 V120 Z" />
      </g>
      {/* ARoS "Your rainbow panorama" */}
      <ellipse cx="314" cy="68" rx="40" ry="7" fill="none" stroke="url(#aros-rainbow)" strokeWidth="4.5" />
    </>
  )
}

function Bucharest() {
  return (
    <>
      <g className="skyline-far">
        <path d="M0 120 V108 H120 V104 H170 V108 H400 V120 Z" />
        {/* trees */}
        <circle cx="160" cy="108" r="7" />
        <circle cx="338" cy="108" r="8" />
      </g>
      <g className="skyline-near">
        {/* Arcul de Triumf */}
        <path fillRule="evenodd" d="M16 76 H74 V68 H16 Z M20 120 V76 H70 V120 H56 V98 A11 11 0 0 0 34 98 V120 Z" />
        {/* Romanian Athenaeum */}
        <path d="M88 120 V94 H152 V120 Z M94 94 Q120 52 146 94 Z M117 64 H123 V52 H117 Z" />
        {/* Palace of the Parliament */}
        <path d="M172 120 V96 H328 V120 Z M190 96 V84 H310 V96 Z M214 84 V72 H286 V84 Z M238 72 V56 H262 V72 Z M245 56 V47 H255 V56 Z" />
        {/* InterContinental tower */}
        <path d="M352 120 V44 H372 V120 Z M356 44 V38 H368 V44 Z" />
      </g>
    </>
  )
}
