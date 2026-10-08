import { Link } from 'react-router-dom'
import { METHOD_ICONS } from '../constants/payment'
import { formatCurrency, formatDateTime } from '../utils/format'
import { CardIcon } from './Icons'
import StatusBadge from './StatusBadge'

export default function TransactionRow({ transaction }) {
  const Icon = METHOD_ICONS[transaction.payment_method] || CardIcon
  return (
    <Link to={`/transactions/${transaction.transaction_id}`} className="txn-row">
      <span className="txn-row__icon"><Icon width={20} height={20} /></span>
      <span className="txn-row__main">
        <strong>{transaction.recipient_name}</strong>
        <small>{transaction.transaction_id}</small>
      </span>
      <span className="txn-row__meta">
        {transaction.payment_method_label} · {formatDateTime(transaction.created_at)}
      </span>
      <span className="txn-row__amount">{formatCurrency(transaction.amount, transaction.currency)}</span>
      <span className="txn-row__status"><StatusBadge status={transaction.status} label={transaction.status_label} /></span>
    </Link>
  )
}
