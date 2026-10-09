import { Link } from 'react-router-dom'
import StatusBadge from '../StatusBadge'
import { formatCurrency, formatDateTime } from '../../utils/format'

/** Admin transaction table. The fraud-analysis column only appears if any row has a real result. */
export default function TransactionTable({ transactions, showSender = true }) {
  const showFraud = transactions.some((transaction) => transaction.fraud_analysis)
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Transaction ID</th>
            <th>Date</th>
            {showSender && <th>Sender</th>}
            <th>Recipient</th>
            <th className="table__num">Amount</th>
            <th>Method</th>
            <th>Status</th>
            {showFraud && <th>Fraud analysis</th>}
          </tr>
        </thead>
        <tbody>
          {transactions.map((txn) => (
            <tr key={txn.transaction_id}>
              <td><Link to={`/admin/transactions/${txn.transaction_id}`} className="mono">{txn.transaction_id}</Link></td>
              <td className="table__nowrap">{formatDateTime(txn.created_at)}</td>
              {showSender && (
                <td><span className="table__main">{txn.sender_name}</span><span className="table__sub">{txn.sender_email}</span></td>
              )}
              <td><span className="table__main">{txn.recipient_name}</span><span className="table__sub">{txn.recipient_email}</span></td>
              <td className="table__num">{formatCurrency(txn.amount, txn.currency)}</td>
              <td>{txn.payment_method_label}</td>
              <td><StatusBadge status={txn.status} label={txn.status_label} /></td>
              {showFraud && <td>{txn.fraud_analysis || '—'}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
