import { useMemo, useState } from 'react'
import AdminShell from '../../components/admin/AdminShell'
import DateInput from '../../components/admin/DateInput'
import { DataState } from '../../components/admin/PageState'
import Pagination from '../../components/admin/Pagination'
import TransactionTable from '../../components/admin/TransactionTable'
import Button from '../../components/Button'
import { SearchIcon } from '../../components/Icons'
import SelectField from '../../components/SelectField'
import { PAYMENT_METHODS } from '../../constants/payment'
import { useApi } from '../../hooks/useApi'
import { adminService } from '../../services/adminService'

const EMPTY_FILTERS = { q: '', status: '', payment_method: '', date_from: '', date_to: '', ordering: '-created_at' }
const STATUS_OPTIONS = ['PENDING', 'COMPLETED', 'FAILED', 'CANCELLED'].map((value) => ({ value, label: value[0] + value.slice(1).toLowerCase() }))
const METHOD_OPTIONS = PAYMENT_METHODS.map(({ value, label }) => ({ value, label }))
const SORT_OPTIONS = [
  { value: '-created_at', label: 'Newest first' },
  { value: 'created_at', label: 'Oldest first' },
  { value: '-amount', label: 'Amount: high to low' },
  { value: 'amount', label: 'Amount: low to high' },
]

export default function AdminTransactions() {
  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const params = useMemo(() => ({ ...filters, page }), [filters, page])
  const { data, error, isLoading, reload } = useApi(() => adminService.transactions(params), JSON.stringify(params))

  const rangeInvalid = draft.date_from && draft.date_to && draft.date_from > draft.date_to

  const apply = (event) => {
    event.preventDefault()
    if (rangeInvalid) return
    setPage(1)
    setFilters({ ...draft, q: draft.q.trim() })
  }
  const reset = () => {
    setDraft(EMPTY_FILTERS)
    setFilters(EMPTY_FILTERS)
    setPage(1)
  }
  const set = (name) => (event) => setDraft({ ...draft, [name]: event.target.value })

  return (
    <AdminShell title="Transactions">
      <div className="stack">
        <form className="card toolbar toolbar--card" onSubmit={apply}>
          <div className="toolbar__field toolbar__field--grow">
            <label className="field__label" htmlFor="txn-search">Search</label>
            <div className="field__control">
              <SearchIcon className="field__icon" />
              <input id="txn-search" className="field__input" placeholder="Transaction ID, sender or recipient" value={draft.q}
                onChange={set('q')} maxLength={100} />
            </div>
          </div>
          <div className="toolbar__field"><SelectField label="Status" placeholder="All statuses" options={STATUS_OPTIONS} value={draft.status} onChange={set('status')} /></div>
          <div className="toolbar__field"><SelectField label="Payment method" placeholder="All methods" options={METHOD_OPTIONS} value={draft.payment_method} onChange={set('payment_method')} /></div>
          <DateInput label="From" value={draft.date_from} onChange={(date_from) => setDraft({ ...draft, date_from })} />
          <DateInput label="To" value={draft.date_to} onChange={(date_to) => setDraft({ ...draft, date_to })} />
          <div className="toolbar__field">
            <label className="field__label" htmlFor="txn-sort">Sort by</label>
            <div className="field__control">
              <select id="txn-sort" className="field__input field__input--plain field__select" value={draft.ordering} onChange={set('ordering')}>
                {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </div>
          </div>
          {rangeInvalid && <p className="field__error toolbar__error">The start date must not be after the end date.</p>}
          <div className="toolbar__actions">
            <Button type="submit" disabled={Boolean(rangeInvalid)}>Apply</Button>
            <Button type="button" variant="secondary" onClick={reset}>Reset</Button>
          </div>
        </form>

        <DataState data={data} error={error} isLoading={isLoading} onRetry={reload} errorMessage="We couldn't load transactions.">
          {data && (
            <section className="card card--list">
              {data.results.length === 0
                ? <p className="chart-card__empty">No transactions match these filters.</p>
                : <TransactionTable transactions={data.results} />}
              <p className="table__count">{data.count} {data.count === 1 ? 'transaction' : 'transactions'}</p>
              <Pagination page={page} count={data.count} onChange={setPage} disabled={isLoading} />
            </section>
          )}
        </DataState>
      </div>
    </AdminShell>
  )
}
