import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import AdminShell from '../../components/admin/AdminShell'
import DateInput from '../../components/admin/DateInput'
import { DataState } from '../../components/admin/PageState'
import Pagination from '../../components/admin/Pagination'
import Button from '../../components/Button'
import { SearchIcon } from '../../components/Icons'
import SelectField from '../../components/SelectField'
import { useApi } from '../../hooks/useApi'
import { adminService } from '../../services/adminService'
import { formatDate } from '../../utils/format'

const EMPTY_FILTERS = { q: '', account_status: '', date_from: '', date_to: '' }
const STATUS_OPTIONS = [{ value: 'active', label: 'Active' }, { value: 'inactive', label: 'Inactive' }]

export default function AdminUsers() {
  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const params = useMemo(() => ({ ...filters, page }), [filters, page])
  const { data, error, isLoading, reload } = useApi(() => adminService.users(params), JSON.stringify(params))

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

  return (
    <AdminShell title="User Management">
      <div className="stack">
        <form className="card toolbar toolbar--card" onSubmit={apply}>
          <div className="toolbar__field toolbar__field--grow">
            <label className="field__label" htmlFor="user-search">Search</label>
            <div className="field__control">
              <SearchIcon className="field__icon" />
              <input id="user-search" className="field__input" placeholder="Name or email" value={draft.q}
                onChange={(event) => setDraft({ ...draft, q: event.target.value })} maxLength={100} />
            </div>
          </div>
          <div className="toolbar__field">
            <SelectField label="Account status" placeholder="All accounts" options={STATUS_OPTIONS} value={draft.account_status}
              onChange={(event) => setDraft({ ...draft, account_status: event.target.value })} />
          </div>
          <DateInput label="Registered from" value={draft.date_from} onChange={(date_from) => setDraft({ ...draft, date_from })} />
          <DateInput label="Registered to" value={draft.date_to} onChange={(date_to) => setDraft({ ...draft, date_to })} />
          {rangeInvalid && <p className="field__error toolbar__error">The start date must not be after the end date.</p>}
          <div className="toolbar__actions">
            <Button type="submit" disabled={Boolean(rangeInvalid)}>Search</Button>
            <Button type="button" variant="secondary" onClick={reset}>Reset</Button>
          </div>
        </form>

        <DataState data={data} error={error} isLoading={isLoading} onRetry={reload} errorMessage="We couldn't load users.">
          {data && (
            <section className="card card--list">
              {data.results.length === 0 ? (
                <p className="chart-card__empty">No users match these filters.</p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr><th>ID</th><th>Name</th><th>Email</th><th>Registered</th><th>Status</th><th className="table__num">Transactions</th></tr>
                    </thead>
                    <tbody>
                      {data.results.map((user) => (
                        <tr key={user.id}>
                          <td>{user.id}</td>
                          <td><Link to={`/admin/users/${user.id}`} className="table__main">{user.full_name}</Link></td>
                          <td>{user.email}</td>
                          <td className="table__nowrap">{formatDate(user.date_joined)}</td>
                          <td><span className={`status-badge status-badge--${user.is_active ? 'completed' : 'failed'}`}>{user.is_active ? 'Active' : 'Inactive'}</span></td>
                          <td className="table__num">{user.transaction_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="table__count">{data.count} {data.count === 1 ? 'user' : 'users'}</p>
              <Pagination page={page} count={data.count} onChange={setPage} disabled={isLoading} />
            </section>
          )}
        </DataState>
      </div>
    </AdminShell>
  )
}
