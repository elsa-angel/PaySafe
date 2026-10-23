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
        <div className="card__title"><h2>Fraud model status</h2><span className="badge">{model.status}</span></div>
        <p className="notice__message">{model.message}</p>
        <dl className="details">
          <div><dt>Model</dt><dd>{model.model} ({model.mode} mode)</dd></div>
          <div><dt>Version</dt><dd>{model.version || NA}</dd></div>
          <div><dt>Decision threshold</dt><dd>{model.threshold === null ? NA : `${model.threshold.toFixed(4)}${model.threshold_source === 'configured_override' ? ' (configured override)' : ' (chosen on Phase 1 validation data)'}`}</dd></div>
          <div><dt>Payment methods it can evaluate</dt><dd>{model.supported_payment_methods.join(', ')}</dd></div>
          <div><dt>Confirmed fraud labels</dt><dd>{labels.available ? 'Available' : NA}</dd></div>
        </dl>
        <ul className="model-limits">{model.limitations.map((text) => <li key={text}>{text}</li>)}</ul>
        <p className="notice__fine">{labels.message}</p>
      </section>

      <PredictionSection predictions={data.predictions} groupBy={groupBy} />

      <ResponseSection response={data.fraud_response} groupBy={groupBy} />

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

const FLAG_COLORS = { flagged: CHART_COLORS.coral, notFlagged: CHART_COLORS.green }

export function ResponseSection({ response: r, groupBy }) {
  const activeRows = r.series.filter((x) => x.high_risk_alerts || x.otp_verified || x.otp_failed || x.cancelled || x.unavailable)
  return (
    <section className="stack" aria-label="Fraud response">
      <div className="section-head">
        <h2>Fraud response (OTP and alerts)</h2>
        <p>Counts come from stored workflow records. One-time codes are never stored in readable form and are not shown. {r.note}</p>
      </div>
      <div className="stat-grid">
        <StatCard label="Low-risk, awaiting OTP" value={r.awaiting.low_risk_awaiting_otp} hint="Code e-mailed, not yet entered" />
        <StatCard tone="amber" label="High-risk, awaiting user" value={r.awaiting.high_risk_awaiting_user_decision} hint="Continue or cancel pending" />
        <StatCard tone="amber" label="High-risk, awaiting OTP" value={r.awaiting.high_risk_awaiting_otp_after_continue} hint="User chose to continue" />
        <StatCard tone="coral" label="Blocked: prediction unavailable" value={r.awaiting.prediction_unavailable_blocked} hint="Cannot proceed" />
      </div>
      <div className="stat-grid">
        <StatCard tone="green" label="Verified with OTP" value={r.outcomes.verified} hint={`${r.otp.incorrect_attempts} incorrect attempt(s) overall`} />
        <StatCard label="Cancelled by user" value={r.outcomes.cancelled_by_user} />
        <StatCard label="Failed, expired or invalidated" value={r.outcomes.failed + r.outcomes.expired + r.outcomes.invalidated_details_changed} hint={`${r.outcomes.failed} failed, ${r.outcomes.expired} expired, ${r.outcomes.invalidated_details_changed} details changed`} />
        <StatCard label="E-mails that failed" value={r.otp.emails_failed + r.high_risk.alert_delivery_failed} hint={`${r.otp.emails_failed} code, ${r.high_risk.alert_delivery_failed} alert`} />
      </div>
      <section className="card">
        <div className="card__title"><h3>Fraud-response activity (per {groupBy})</h3></div>
        {activeRows.length === 0 ? (
          <p className="verify__fine">No fraud-response activity in this period.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Period</th><th className="table__num">High-risk alerts</th><th className="table__num">Verified</th><th className="table__num">Incorrect codes</th><th className="table__num">Cancelled</th><th className="table__num">Unavailable</th></tr>
              </thead>
              <tbody>
                {activeRows.map((x) => (
                  <tr key={x.period}>
                    <td>{formatPeriod(x.period, groupBy)}</td>
                    <td className="table__num">{x.high_risk_alerts}</td><td className="table__num">{x.otp_verified}</td>
                    <td className="table__num">{x.otp_failed}</td><td className="table__num">{x.cancelled}</td><td className="table__num">{x.unavailable}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  )
}

export function PredictionSection({ predictions: p, groupBy }) {
  const evaluated = p.evaluated
  const pct = (value) => (value === null ? NA : `${(value * 100).toFixed(1)}%`)
  return (
    <section className="stack" aria-label="Model predictions">
      <div className="section-head">
        <h2>XGBoost predictions</h2>
        <p>Counts come from stored model results. Unavailable predictions are excluded from class and score figures. A flagged payment is a prediction, not confirmed fraud.</p>
      </div>
      <div className="stat-grid">
        <StatCard label="Evaluated by the model" value={evaluated} hint="Genuine predictions" />
        <StatCard tone="amber" label="Prediction unavailable" value={p.unavailable} hint="Outside what the model supports" />
        <StatCard tone="coral" label="Analysis errors" value={p.error} hint="Technical failures" />
        <StatCard tone="green" label="Not evaluated" value={p.not_evaluated} hint="No analysis recorded (e.g. older payments)" />
      </div>
      <div className="chart-grid">
        <ChartCard title="Predicted classes" subtitle="Evaluated transactions only" isEmpty={evaluated === 0} emptyMessage="No transactions have been evaluated in this period.">
          <DonutChart centerLabel="Evaluated" segments={[
            { label: 'Flagged by model', value: p.predicted_classes.flagged, color: FLAG_COLORS.flagged },
            { label: 'Not flagged', value: p.predicted_classes.not_flagged, color: FLAG_COLORS.notFlagged },
          ]} />
        </ChartCard>
        <ChartCard title="Model score distribution" subtitle={`Evaluated only. Average ${p.probability.average === null ? NA : p.probability.average.toFixed(3)}; share flagged ${pct(p.predicted_classes.flagged_share)}`}
          isEmpty={evaluated === 0} emptyMessage="No scores yet.">
          <BarChart integer ariaLabel="Model score distribution" color={CHART_COLORS.blue}
            points={p.probability.histogram.map((b) => ({ label: `${b.from.toFixed(1)}`, value: b.count, tooltip: `Score ${b.from.toFixed(1)} to ${b.to.toFixed(1)}: ${b.count}` }))} />
        </ChartCard>
        <ChartCard title="Evaluated transactions" subtitle={`Per ${groupBy}`} isEmpty={evaluated === 0} wide>
          <LineChart integer ariaLabel="Evaluated transactions over time"
            points={p.series.map((x) => ({ label: formatPeriod(x.period, groupBy), value: x.evaluated, tooltip: `${formatPeriod(x.period, groupBy)}: ${x.evaluated} evaluated, ${x.flagged} flagged` }))} />
        </ChartCard>
      </div>
      {p.unavailable_by_category.length > 0 && (
        <section className="card">
          <div className="card__title"><h3>Why predictions were unavailable</h3></div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Outcome</th><th>Reason</th><th className="table__num">Transactions</th></tr></thead>
              <tbody>
                {p.unavailable_by_category.map((r) => (
                  <tr key={`${r.status}-${r.category}`}><td>{r.status === 'ERROR' ? 'Error' : 'Unavailable'}</td><td>{r.message}</td><td className="table__num">{r.count}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </section>
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
