import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import AdminShell from '../../components/admin/AdminShell'
import { BarChart, DonutChart, HBars, LineChart } from '../../components/admin/Charts'
import ChartCard from '../../components/admin/ChartCard'
import DateRangeFilter from '../../components/admin/DateRangeFilter'
import { DataState } from '../../components/admin/PageState'
import StatCard from '../../components/admin/StatCard'
import TransactionTable from '../../components/admin/TransactionTable'
import { ActivityIcon, ListIcon, ShieldIcon, UserIcon } from '../../components/Icons'
import { useApi } from '../../hooks/useApi'
import { CHART_COLORS } from '../../utils/chartColors'
import { DEFAULT_RANGE, rangeToParams } from '../../utils/dateRange'
import { adminService } from '../../services/adminService'
import { formatCompact, formatCurrency, formatPeriod } from '../../utils/format'

const STATUS_COLORS = { PENDING: CHART_COLORS.amber, COMPLETED: CHART_COLORS.green, FAILED: CHART_COLORS.coral, CANCELLED: CHART_COLORS.muted }

export default function AdminOverview() {
  const [range, setRange] = useState(DEFAULT_RANGE)
  const params = useMemo(() => rangeToParams(range), [range])
  const { data, error, isLoading, reload } = useApi(() => adminService.overview(params), JSON.stringify(params))

  return (
    <AdminShell title="Overview">
      <div className="stack">
        <DateRangeFilter value={range} onChange={setRange} showGroupBy />
        <DataState data={data} error={error} isLoading={isLoading} onRetry={reload} errorMessage="We couldn't load the overview.">
          {data && <OverviewContent data={data} />}
        </DataState>
      </div>
    </AdminShell>
  )
}

function OverviewContent({ data }) {
  const { users, transactions: t, charts, currency } = data
  const groupBy = data.period.group_by
  const money = (value) => formatCurrency(value, currency)
  const activity = charts.activity
  const hasTransactions = t.total_transactions > 0

  return (
    <div className="stack">
      <section className="stat-grid" aria-label="Summary">
        <StatCard icon={UserIcon} label="Registered users" value={users.total} hint={`${users.new_in_period} new in this period · ${users.inactive} inactive`} />
        <StatCard icon={ListIcon} label="Transactions" value={t.total_transactions} hint="All statuses, this period" />
        <StatCard tone="green" icon={ShieldIcon} label="Completed" value={t.completed} />
        <StatCard tone="amber" icon={ActivityIcon} label="Pending" value={t.pending} />
        <StatCard tone="coral" icon={ActivityIcon} label="Failed" value={t.failed} />
        <StatCard tone="muted" icon={ActivityIcon} label="Cancelled" value={t.cancelled} />
        <StatCard tone="green" label="Total amount" value={money(t.total_amount)} hint="Completed transactions only" />
        <StatCard tone="green" label="Average amount" value={t.average_amount === null ? 'Not available' : money(t.average_amount)} hint="Completed transactions only" />
      </section>

      <div className="chart-grid">
        <ChartCard title="Transaction activity" subtitle={`Number of transactions per ${groupBy}`} isEmpty={!hasTransactions} wide>
          <LineChart integer ariaLabel="Transaction count over time"
            points={activity.map((p) => ({ label: formatPeriod(p.period, groupBy), value: p.count, tooltip: `${formatPeriod(p.period, groupBy)}: ${p.count} transactions` }))} />
        </ChartCard>
        <ChartCard title="Transaction amounts" subtitle={`Completed amount per ${groupBy}`} isEmpty={!hasTransactions || t.completed === 0}
          emptyMessage="No completed transactions in this period." wide>
          <BarChart ariaLabel="Completed transaction amount over time" color={CHART_COLORS.green} formatValue={formatCompact}
            points={activity.map((p) => ({ label: formatPeriod(p.period, groupBy), value: Number(p.amount), tooltip: `${formatPeriod(p.period, groupBy)}: ${money(p.amount)}` }))} />
        </ChartCard>
        <ChartCard title="Status distribution" isEmpty={!hasTransactions}>
          <DonutChart centerLabel="Transactions"
            segments={charts.status_distribution.map((s) => ({ label: s.label, value: s.count, color: STATUS_COLORS[s.value] }))} />
        </ChartCard>
        <ChartCard title="Payment methods" subtitle="Transactions per method" isEmpty={!hasTransactions}>
          <HBars rows={charts.method_distribution.map((m) => ({ label: m.label, value: m.count }))} />
        </ChartCard>
        <ChartCard title="User registrations" subtitle={`New users per ${groupBy}`} isEmpty={users.new_in_period === 0} emptyMessage="No new registrations in this period." wide>
          <BarChart integer ariaLabel="New user registrations over time" color={CHART_COLORS.blue}
            points={charts.registrations.map((p) => ({ label: formatPeriod(p.period, groupBy), value: p.count, tooltip: `${formatPeriod(p.period, groupBy)}: ${p.count} new users` }))} />
        </ChartCard>
      </div>

      <section className="card">
        <div className="card__title"><h2>Recent transaction activity</h2><Link to="/admin/transactions" className="recent__all">View all</Link></div>
        {data.recent_transactions.length === 0
          ? <p className="chart-card__empty">No transactions have been made yet.</p>
          : <TransactionTable transactions={data.recent_transactions} />}
      </section>
    </div>
  )
}
