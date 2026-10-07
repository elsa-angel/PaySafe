/** Original PaySafe illustration: a phone-and-shield with a payment card and coins. */
export default function HeroIllustration() {
  return (
    <svg className="hero-art" viewBox="0 0 460 400" role="img" aria-label="A phone showing a protected payment">
      {/* decorative shapes */}
      <path d="M40 170a52 52 0 0 1 52-52v52Z" fill="#f8b76a" stroke="#1f2a44" strokeWidth="2" />
      <path d="M392 288a44 44 0 0 0 44 44v-44Z" fill="#e2616f" stroke="#1f2a44" strokeWidth="2" />
      <path d="M356 60l34 52h-68Z" fill="#5b7fe3" stroke="#1f2a44" strokeWidth="2" strokeLinejoin="round" />
      <g stroke="#e2616f" strokeWidth="2.5" strokeLinecap="round">
        <path d="M70 70v16M62 78h16" />
        <path d="M410 190v14M403 197h14" stroke="#5b7fe3" />
        <path d="M120 330v12M114 336h12" stroke="#f8b76a" />
      </g>
      <path d="M10 240c60-40 90 40 150 0" fill="none" stroke="#5b7fe3" strokeWidth="2" />
      <path d="M300 30c40 30 80-10 150 20" fill="none" stroke="#e2616f" strokeWidth="2" />

      {/* credit card behind phone */}
      <g transform="rotate(-12 120 230)">
        <rect x="46" y="190" width="170" height="106" rx="16" fill="#f8b76a" stroke="#1f2a44" strokeWidth="2" />
        <rect x="46" y="212" width="170" height="20" fill="#1f2a44" opacity=".85" />
        <rect x="62" y="252" width="70" height="8" rx="4" fill="#fff" opacity=".85" />
        <rect x="62" y="270" width="44" height="8" rx="4" fill="#fff" opacity=".6" />
        <circle cx="190" cy="274" r="12" fill="#e2616f" opacity=".9" />
        <circle cx="178" cy="274" r="12" fill="#fff" opacity=".55" />
      </g>

      {/* phone */}
      <rect x="170" y="40" width="190" height="330" rx="30" fill="#5b7fe3" stroke="#1f2a44" strokeWidth="2.5" />
      <rect x="182" y="56" width="166" height="298" rx="22" fill="#fdf6e8" />
      <rect x="236" y="62" width="58" height="8" rx="4" fill="#1f2a44" opacity=".15" />
      {/* shield */}
      <path d="M265 104 218 124v34c0 28 19 50 47 62 28-12 47-34 47-62v-34l-47-20Z" fill="#5b7fe3" stroke="#1f2a44" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M265 104v116c28-12 47-34 47-62v-34l-47-20Z" fill="#1f2a44" opacity=".12" />
      <path d="m245 160 15 15 28-32" fill="none" stroke="#fff" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
      {/* receipt rows */}
      <rect x="198" y="246" width="134" height="30" rx="12" fill="#fff" stroke="#e7e9f2" />
      <circle cx="215" cy="261" r="7" fill="#f8b76a" />
      <rect x="230" y="256" width="52" height="6" rx="3" fill="#1f2a44" opacity=".7" />
      <rect x="230" y="266" width="32" height="4" rx="2" fill="#1f2a44" opacity=".25" />
      <rect x="198" y="286" width="134" height="30" rx="12" fill="#fff" stroke="#e7e9f2" />
      <circle cx="215" cy="301" r="7" fill="#e2616f" />
      <rect x="230" y="296" width="44" height="6" rx="3" fill="#1f2a44" opacity=".7" />
      <rect x="230" y="306" width="28" height="4" rx="2" fill="#1f2a44" opacity=".25" />

      {/* coins */}
      {[[372, 250], [398, 232], [352, 304]].map(([x, y]) => (
        <g key={`${x}-${y}`}>
          <circle cx={x} cy={y} r="17" fill="#f8b76a" stroke="#1f2a44" strokeWidth="2" />
          <circle cx={x} cy={y} r="10" fill="none" stroke="#1f2a44" strokeWidth="1.5" opacity=".5" />
          <path d={`M${x - 3} ${y - 4}h6M${x - 3} ${y + 4}h6M${x} ${y - 6}v12`} stroke="#1f2a44" strokeWidth="1.6" strokeLinecap="round" opacity=".7" />
        </g>
      ))}
    </svg>
  )
}
