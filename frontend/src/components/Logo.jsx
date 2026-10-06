export default function Logo({ light = false, size = 36 }) {
  return (
    <span className={`logo${light ? ' logo--light' : ''}`}>
      <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
        <path
          d="M20 3 6 8.5v10.2c0 8.3 5.6 14.4 14 18.3 8.4-3.9 14-10 14-18.3V8.5L20 3Z"
          fill="var(--logo-shield, #5b7fe3)"
        />
        <path d="M20 3v34c8.4-3.9 14-10 14-18.3V8.5L20 3Z" fill="#000" opacity=".1" />
        <path d="m13.5 20.5 4.8 4.8 8.2-9.3" fill="none" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="31.5" cy="9" r="4.2" fill="#f8b76a" />
      </svg>
      <span className="logo__text">PaySafe</span>
    </span>
  )
}
