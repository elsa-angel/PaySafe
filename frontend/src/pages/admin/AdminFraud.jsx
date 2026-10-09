import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import AdminShell from '../../components/admin/AdminShell'
import { BarChart, DonutChart, HBars, LineChart } from '../../components/admin/Charts'
import ChartCard from '../../components/admin/ChartCard'
import DateRangeFilter from '../../components/admin/DateRangeFilter'
import { DataState } from '../../components/admin/PageState'
import StatCard from '../../components/admin/StatCard'
import Alert from '../../components/Alert'
import StatusBadge from '../../components/StatusBadge'
import { useApi } from '../../hooks/useApi'
import { CHART_COLORS } from '../../utils/chartColors'
import { DEFAULT_RANGE, rangeToParams } from '../../utils/dateRange'
import { adminService } from '../../services/adminService'
import { formatCompact, formatCurrency, formatDateTime, formatPeriod } from '../../utils/format'

const STATUS_COLORS = { PENDING: CHART_COLORS.amber, COMPLETED: CHART_COLORS.green, FAILED: CHART_COLORS.coral, CANCELLED: CHART_COLORS.muted }
const NA = 'Not available'

export default function AdminFraud() {
  const [range, setRange] = useState(DEFAULT_RANGE)
  const params = useMemo(() => rangeToParams(range), [range])
  const { data, error, isLoading, reload } = useApi(() => adminService.fraudStatistics(params), JSON.stringify(params))

  return (
    <AdminShell title="Fraud Statistics">
      <div className="stack">
        <DateRangeFilter value={range} onChange={setRange} showGroupBy />
        <DataState data={data} error={error} isLoading={isLoading} onRetry={reload} errorMessage="We couldn't load fraud statistics.">
          {data && <FraudContent data={data} />}
        </DataState>
      </div>
    </AdminShell>
  )
}

function FraudContent({ data }) {
  const { ml_model: model, confirmed_fraud: labels, activity, rule_based: rules, currency } = data
  const groupBy = data.period.group_by
  const money = (value) => (value === null ? NA : formatCurrency(value, currency))
  const summary = activity.summary
  const hasTransactions = summary.total_transactions > 0

  return (
    <div className="stack">
      <section className="card notice">
        <div className="card__title"><h2>Fraud detection status</h2><span className="badge">{model.status}</span></div>
        <p className="notice__message">{model.message}</p>
        <dl className="details">
          <div><dt>ML model</dt><dd>{model.model}: {model.status}</dd></div>
          <div><dt>Confirmed fraud labels</dt><dd>{labels.available ? 'Available' : NA}</dd></div>
          <div><dt>ML predictions and risk scores</dt><dd>{NA}</dd></div>
        </dl>
        <p className="notice__fine">{labels.message}</p>
      </section>

      <section className="stat-grid" aria-label="Transaction activity">
        <StatCard label="Total transactions" value={summary.total_transactions} hint="All statuses, this period" />
        <StatCard tone="green" label="Average amount" value={money(summary.average_amount)} hint="Completed only" />
        <StatCard tone="amber" label="Minimum amount" value={money(summary.min_amount)} hint="Completed only" />
        <StatCard tone="coral" label="Maximum amount" value={money(summary.max_amount)} hint="Completed only" />
      </section>

      <div className="chart-grid">
        <ChartCard title="Transaction volume" subtitle={`Transactions per ${groupBy}`} isEmpty={!hasTransactions} wide>
          <LineChart integer ariaLabel="Transaction volume over time"
            points={activity.series.map((p) => ({ label: formatPeriod(p.period, groupBy), value: p.count, tooltip: `${formatPeriod(p.period, groupBy)}: ${p.count} transactions` }))} />
        </ChartCard>
        <ChartCard title="Transaction amounts" subtitle={`Completed amount per ${groupBy}`} isEmpty={!hasTransactions || summary.completed === 0}
          emptyMessage="No completed transactions in this period." wide>
          <BarChart ariaLabel="Completed amount over time" color={CHART_COLORS.green} formatValue={formatCompact}
            points={activity.series.map((p) => ({ label: formatPeriod(p.period, groupBy), value: Number(p.amount), tooltip: `${formatPeriod(p.period, groupBy)}: ${money(p.amount)}` }))} />
        </ChartCard>
        <ChartCard title="Status distribution" isEmpty={!hasTransactions}>
          <DonutChart centerLabel="Transactions"
            segments={activity.status_distribution.map((s) => ({ label: s.label, value: s.count, color: STATUS_COLORS[s.value] }))} />
        </ChartCard>
        <ChartCard title="Payment methods" subtitle="Transactions per method" isEmpty={!hasTransactions}>
          <HBars rows={activity.method_distribution.map((m) => ({ label: m.label, value: m.count }))} />
        </ChartCard>
      </div>

      <section className="stack">
        <div className="section-head">
          <h2>Preliminary rule-based monitoring</h2>
          <p>{rules.disclaimer}</p>
        </div>
        {rules.indicators.map((rule) => <RuleCard key={rule.id} rule={rule} currency={currency} />)}
      </section>
    </div>
  )
}

function RuleCard({ rule, currency }) {
  return (
    <section className="card rule">
      <div className="rule__head">
        <div>
          <h3>{rule.name}</h3>
          <p>{rule.description}</p>
          <p className="rule__threshold">Rule: {rule.threshold}</p>
        </div>
        <div className="rule__count">
          <strong>{rule.available ? rule.flagged_count : NA}</strong>
          <span>{rule.available ? 'flagged' : ''}</span>
        </div>
      </div>
      {!rule.available && <Alert variant="info">{rule.reason}</Alert>}
      {rule.available && rule.flagged_count === 0 && <p className="chart-card__empty">Nothing matched this rule in the selected period.</p>}
      {rule.available && rule.flagged_transactions.length > 0 && (
        <details className="rule__details">
          <summary>Show most recent flagged transactions ({rule.flagged_transactions.length} of {rule.flagged_count})</summary>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Transaction ID</th><th>Date</th><th>Sender</th><th className="table__num">Amount</th><th>Status</th></tr></thead>
              <tbody>
                {rule.flagged_transactions.map((t) => (
                  <tr key={t.transaction_id}>
                    <td><Link to={`/admin/transactions/${t.transaction_id}`} className="mono">{t.transaction_id}</Link></td>
                    <td className="table__nowrap">{formatDateTime(t.created_at)}</td>
                    <td>{t.sender_email}</td>
                    <td className="table__num">{formatCurrency(t.amount, t.currency || currency)}</td>
                    <td><StatusBadge status={t.status} label={t.status_label} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  )
}
