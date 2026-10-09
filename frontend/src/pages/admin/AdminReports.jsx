import { useMemo, useState } from 'react'
import AdminShell from '../../components/admin/AdminShell'
import DateRangeFilter from '../../components/admin/DateRangeFilter'
import Alert from '../../components/Alert'
import Button from '../../components/Button'
import { DownloadIcon } from '../../components/Icons'
import SelectField from '../../components/SelectField'
import { PAYMENT_METHODS } from '../../constants/payment'
import { adminService } from '../../services/adminService'
import { rangeToParams } from '../../utils/dateRange'
import { formatCurrency, formatDateTime } from '../../utils/format'
import { parseApiError } from '../../utils/validation'

const REPORT_TYPES = [
  { value: 'transactions', label: 'Transaction Summary', description: 'Counts by status, completed amounts, and breakdowns by method and status.', filters: ['status', 'payment_method'] },
  { value: 'users', label: 'User Registration', description: 'New registrations over time and account-status breakdown.', filters: ['account_status', 'group_by'] },
  { value: 'activity', label: 'Transaction Activity', description: 'Transaction counts and amounts over time, with breakdowns.', filters: ['status', 'payment_method', 'group_by'] },
  { value: 'fraud-monitoring', label: 'Fraud Monitoring', description: 'Activity statistics and preliminary rule-based indicators. No ML predictions.', filters: ['status', 'payment_method'] },
]
const STATUS_OPTIONS = ['PENDING', 'COMPLETED', 'FAILED', 'CANCELLED'].map((value) => ({ value, label: value[0] + value.slice(1).toLowerCase() }))
const METHOD_OPTIONS = PAYMENT_METHODS.map(({ value, label }) => ({ value, label }))
const ACCOUNT_OPTIONS = [{ value: 'active', label: 'Active' }, { value: 'inactive', label: 'Inactive' }]
const GROUP_OPTIONS = [{ value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }]

const INITIAL_RANGE = { preset: 'all', from: '', to: '', groupBy: '' }
const INITIAL_FILTERS = { status: '', payment_method: '', account_status: '', group_by: '' }

export default function AdminReports() {
  const [kind, setKind] = useState('transactions')
  const [range, setRange] = useState(INITIAL_RANGE)
  const [filters, setFilters] = useState(INITIAL_FILTERS)
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState('') // '' | 'preview' | 'download'
  const [error, setError] = useState('')

  const type = REPORT_TYPES.find((candidate) => candidate.value === kind)
  const params = useMemo(() => {
    const result = { ...rangeToParams(range) }
    for (const name of type.filters) if (filters[name]) result[name] = filters[name]
    return result
  }, [range, filters, type])

  const changed = (apply) => (...args) => {
    apply(...args)
    setReport(null)
    setError('')
  }
  const rangeInvalid = range.preset === 'custom' && range.from && range.to && range.from > range.to

  const run = (mode) => async () => {
    setBusy(mode)
    setError('')
    try {
      if (mode === 'preview') {
        setReport(await adminService.report(kind, params))
      } else {
        const { blob, filename } = await adminService.downloadReport(kind, params)
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        document.body.append(link)
        link.click()
        link.remove()
        URL.revokeObjectURL(url)
      }
    } catch (apiError) {
      setError(parseApiError(apiError).formError)
    } finally {
      setBusy('')
    }
  }

  const filterField = {
    status: <SelectField key="status" label="Status" placeholder="All statuses" options={STATUS_OPTIONS} value={filters.status} onChange={changed((e) => setFilters({ ...filters, status: e.target.value }))} />,
    payment_method: <SelectField key="payment_method" label="Payment method" placeholder="All methods" options={METHOD_OPTIONS} value={filters.payment_method} onChange={changed((e) => setFilters({ ...filters, payment_method: e.target.value }))} />,
    account_status: <SelectField key="account_status" label="Account status" placeholder="All accounts" options={ACCOUNT_OPTIONS} value={filters.account_status} onChange={changed((e) => setFilters({ ...filters, account_status: e.target.value }))} />,
    group_by: <SelectField key="group_by" label="Group by" placeholder="Automatic" options={GROUP_OPTIONS} value={filters.group_by} onChange={changed((e) => setFilters({ ...filters, group_by: e.target.value }))} />,
  }

  return (
    <AdminShell title="Reports">
      <div className="stack">
        <section className="card">
          <div className="form-section">
            <h2 className="form-section__title">Report type</h2>
            <div className="report-types" role="radiogroup" aria-label="Report type">
              {REPORT_TYPES.map((option) => (
                <label key={option.value} className={`report-type${kind === option.value ? ' is-selected' : ''}`}>
                  <input type="radio" name="report-type" value={option.value} checked={kind === option.value}
                    onChange={changed(() => setKind(option.value))} />
                  <strong>{option.label}</strong>
                  <span>{option.description}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="form-section report-filters">
            <h2 className="form-section__title">Date range and filters</h2>
            <DateRangeFilter value={range} onChange={changed(setRange)} />
            <div className="report-filters__grid">{type.filters.map((name) => filterField[name])}</div>
          </div>

          <Alert>{error}</Alert>
          <div className="form-actions form-actions--start report-actions">
            <Button type="button" onClick={run('preview')} isLoading={busy === 'preview'} loadingText="Generating…" disabled={Boolean(busy) || rangeInvalid}>
              Generate report
            </Button>
            <Button type="button" variant="secondary" onClick={run('download')} isLoading={busy === 'download'} loadingText="Preparing…" disabled={Boolean(busy) || rangeInvalid}>
              <DownloadIcon width={18} height={18} /> Download CSV
            </Button>
          </div>
        </section>

        {report && <ReportPreview report={report} />}
      </div>
    </AdminShell>
  )
}

const MONEY_TEXT = /^-?\d+(\.\d+)?$/

/** Amount columns/rows arrive as numbers (or numeric text); show them as currency. */
function formatCell(column, label, value) {
  if (value === null || value === undefined) return '—'
  const isAmount = /amount/i.test(column) || /amount/i.test(String(label))
  if (isAmount && (typeof value === 'number' || (typeof value === 'string' && MONEY_TEXT.test(value)))) {
    return formatCurrency(value)
  }
  return String(value)
}

function ReportPreview({ report }) {
  return (
    <section className="card report">
      <header className="report__head">
        <h2>{report.title}</h2>
        <p>Generated {formatDateTime(report.generated_at)}</p>
        <ul className="report__filters">
          {report.filters.map(([label, value]) => <li key={label}><span>{label}</span><strong>{value}</strong></li>)}
        </ul>
        {report.notes.map((note) => <Alert key={note} variant="info">{note}</Alert>)}
      </header>
      {report.sections.map((section) => (
        <div key={section.title} className="report__section">
          <h3>{section.title}</h3>
          {section.rows.length === 0 ? (
            <p className="chart-card__empty">No data for the selected filters.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr>{section.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
                <tbody>
                  {section.rows.map((row, index) => (
                    <tr key={index}>{row.map((cell, i) => <td key={i}>{formatCell(section.columns[i], row[0], cell)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </section>
  )
}
