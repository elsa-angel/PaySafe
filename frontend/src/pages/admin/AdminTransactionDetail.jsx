import { Link, useParams } from 'react-router-dom'
import AdminShell from '../../components/admin/AdminShell'
import { DataState } from '../../components/admin/PageState'
import FraudAnalysisPanel from '../../components/FraudAnalysisPanel'
import StatusBadge from '../../components/StatusBadge'
import { useApi } from '../../hooks/useApi'
import { adminService } from '../../services/adminService'
import { formatCurrency, formatDateTime } from '../../utils/format'

export default function AdminTransactionDetail() {
  const { transactionId } = useParams()
  const { data: txn, error, isLoading, reload } = useApi(() => adminService.transaction(transactionId), transactionId)
  const notFound = error?.status === 404

  return (
    <AdminShell title="Transaction details" eyebrow="Transaction" backTo="/admin/transactions" backLabel="Transactions">
      {notFound ? (
        <section className="card empty-state"><h2>Transaction not found</h2><p>No transaction exists with this ID.</p></section>
      ) : (
        <DataState data={txn} error={error} isLoading={isLoading} onRetry={reload} errorMessage="We couldn't load this transaction.">
          {txn && <Details txn={txn} />}
        </DataState>
      )}
    </AdminShell>
  )
}

function Details({ txn }) {
  const rows = [
    ['Transaction ID', <span className="mono">{txn.transaction_id}</span>],
    ['Date & time', formatDateTime(txn.created_at)],
    ['Status', <StatusBadge status={txn.status} label={txn.status_label} />],
    ['Amount', <strong>{formatCurrency(txn.amount, txn.currency)}</strong>],
    ['Sender', <><Link to={`/admin/users/${txn.sender_id}`}>{txn.sender_name}</Link><small className="details__sub">{txn.sender_email}</small></>],
    ['Recipient', <>{txn.recipient_name}<small className="details__sub">{txn.recipient_email}</small></>],
    ['Payment method', <>{txn.payment_method_label}<small className="details__sub">{txn.payment_method_detail}</small></>],
    ['Note', txn.description || '—'],
    ['Device', `${txn.device_type_label}${txn.browser ? ` · ${txn.browser}` : ''}${txn.operating_system ? ` · ${txn.operating_system}` : ''}`],
    ['Location shared', txn.location_status_label],
    ['Last updated', formatDateTime(txn.updated_at)],
  ]
  if (txn.failure_reason) rows.splice(3, 0, ['Failure reason', txn.failure_reason])

  return (
    <section className="card card--narrow">
      <dl className="receipt">
        {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
      <FraudAnalysisPanel analysis={txn.fraud_analysis_detail} admin />
      {txn.verification && txn.verification.status !== 'NOT_STARTED' && (
        <section className="fraud-panel" aria-label="Verification">
          <div className="fraud-panel__head">
            <h3>Verification (OTP)</h3>
            <span className="fraud-panel__badge">{txn.verification.status_label}</span>
          </div>
          <p className="fraud-panel__message">{txn.verification.message}</p>
          {txn.workflow_events?.length > 0 && (
            <ul className="timeline" aria-label="Workflow events">
              {txn.workflow_events.map((event, index) => (
                <li key={`${event.event_type}-${index}`}>
                  <span>{event.label}{event.detail ? ` (${event.detail})` : ''}</span>
                  <time dateTime={event.created_at}>{formatDateTime(event.created_at)}</time>
                </li>
              ))}
            </ul>
          )}
          <p className="fraud-panel__fine">One-time codes are never stored or shown; only audit events are listed.</p>
        </section>
      )}
    </section>
  )
}
