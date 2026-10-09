export default function StatCard({ label, value, hint, tone = 'blue', icon: Icon }) {
  return (
    <div className={`stat-card stat-card--${tone}`}>
      {Icon && <span className="stat-card__icon"><Icon width={20} height={20} /></span>}
      <span className="stat-card__label">{label}</span>
      <strong className="stat-card__value">{value}</strong>
      {hint && <span className="stat-card__hint">{hint}</span>}
    </div>
  )
}
