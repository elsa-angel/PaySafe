export default function ChartCard({ title, subtitle, isEmpty, emptyMessage = 'No data for this period.', wide = false, children }) {
  return (
    <section className={`card chart-card${wide ? ' chart-card--wide' : ''}`}>
      <header className="chart-card__head">
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </header>
      {isEmpty ? <p className="chart-card__empty">{emptyMessage}</p> : children}
    </section>
  )
}
