import { useState } from 'react'
import { useParams } from 'react-router-dom'
import AdminShell from '../../components/admin/AdminShell'
import { DataState } from '../../components/admin/PageState'
import Pagination from '../../components/admin/Pagination'
import TransactionTable from '../../components/admin/TransactionTable'
import Alert from '../../components/Alert'
import Button from '../../components/Button'
import { useApi } from '../../hooks/useApi'
import { adminService } from '../../services/adminService'
import { formatCurrency, formatDate, formatDateTime } from '../../utils/format'
import { parseApiError } from '../../utils/validation'

export default function AdminUserDetail() {
  const { userId } = useParams()
  const { data: user, error, isLoading, reload } = useApi(() => adminService.user(userId), userId)
  const notFound = error?.status === 404

  return (
    <AdminShell title={user?.full_name || 'User details'} eyebrow="User" backTo="/admin/users" backLabel="User Management">
      {notFound ? (
        <section className="card empty-state">
          <h2>User not found</h2>
          <p>This user doesn't exist or isn't a regular PaySafe account.</p>
        </section>
      ) : (
        <DataState data={user} error={error} isLoading={isLoading} onRetry={reload} errorMessage="We couldn't load this user.">
          {user && (
            <div className="stack">
              <UserCard user={user} onChanged={reload} />
              <UserTransactions userId={userId} />
            </div>
          )}
        </DataState>
      )}
    </AdminShell>
  )
}

function UserCard({ user, onChanged }) {
  const [confirming, setConfirming] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const target = !user.is_active // the state we would switch to

  const changeStatus = async () => {
    setIsSaving(true)
    setError('')
    try {
      await adminService.setUserStatus(user.id, target)
      setConfirming(false)
      onChanged()
    } catch (apiError) {
      setError(parseApiError(apiError).formError)
    } finally {
      setIsSaving(false)
    }
  }

  const details = [
    ['User ID', user.id],
    ['Full name', user.full_name],
    ['Email', user.email],
    ['Registered', formatDateTime(user.date_joined)],
    ['Last sign-in', user.last_login ? formatDateTime(user.last_login) : 'Never'],
    ['Transactions', `${user.transaction_count} (${user.completed_transaction_count} completed)`],
    ['Total completed amount', formatCurrency(user.total_completed_amount || 0)],
    ['Last transaction', user.last_transaction_at ? formatDate(user.last_transaction_at) : 'None yet'],
  ]

  return (
    <section className="card">
      <div className="card__title">
        <h2>Account</h2>
        <span className={`badge${user.is_active ? ' badge--ok' : ''}`}>{user.is_active ? 'Active' : 'Inactive'}</span>
      </div>
      <dl className="details">
        {details.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
      <Alert>{error}</Alert>
      {confirming ? (
        <div className="confirm">
          <p>
            {target
              ? 'Reactivate this account? The user will be able to sign in again.'
              : 'Deactivate this account? The user will be signed out and unable to sign in. Their data and transactions are kept.'}
          </p>
          <div className="form-actions form-actions--start">
            <Button type="button" variant="secondary" onClick={() => setConfirming(false)} disabled={isSaving}>Cancel</Button>
            <Button type="button" onClick={changeStatus} isLoading={isSaving} loadingText="Saving…">
              {target ? 'Yes, activate' : 'Yes, deactivate'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="form-actions form-actions--start">
          <Button type="button" variant={target ? 'primary' : 'secondary'} onClick={() => setConfirming(true)}>
            {target ? 'Activate account' : 'Deactivate account'}
          </Button>
        </div>
      )}
    </section>
  )
}

function UserTransactions({ userId }) {
  const [page, setPage] = useState(1)
  const params = { page }
  const { data, error, isLoading, reload } = useApi(() => adminService.userTransactions(userId, params), `${userId}-${page}`)

  return (
    <section className="card card--list">
      <div className="card__title card__title--padded"><h2>Transaction history</h2></div>
      <DataState data={data} error={error} isLoading={isLoading} onRetry={reload} errorMessage="We couldn't load this user's transactions.">
        {data && (data.results.length === 0
          ? <p className="chart-card__empty">This user hasn't made any transactions yet.</p>
          : <>
              <TransactionTable transactions={data.results} showSender={false} />
              <Pagination page={page} count={data.count} onChange={setPage} disabled={isLoading} />
            </>)}
      </DataState>
    </section>
  )
}
