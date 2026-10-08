import { formatCurrency, formatDateTime } from '../utils/format'
import StatusBadge from './StatusBadge'

/** User-facing transaction facts, shared by the success page and the detail page. */
export default function TransactionDetails({ transaction }) {
  const rows = [
    ['Transaction ID', <span className="mono">{transaction.transaction_id}</span>],
    ['Recipient', <>{transaction.recipient_name}<small className="details__sub">{transaction.recipient_email}</small></>],
    ['Amount', <strong>{formatCurrency(transaction.amount, transaction.currency)}</strong>],
    ['Payment method', <>{transaction.payment_method_label}<small className="details__sub">{transaction.payment_method_detail}</small></>],
    ['Date & time', formatDateTime(transaction.created_at)],
    ['Status', <StatusBadge status={transaction.status} label={transaction.status_label} />],
  ]
  if (transaction.description) rows.splice(4, 0, ['Note', transaction.description])

  return (
    <dl className="receipt">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
