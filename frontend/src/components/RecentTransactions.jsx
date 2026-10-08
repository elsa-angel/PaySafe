import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { paymentService } from '../services/paymentService'
import TransactionRow from './TransactionRow'

const RECENT_COUNT = 4

/** Small dashboard summary. Renders nothing while loading, on error, or when there are no transactions. */
export default function RecentTransactions() {
  const [transactions, setTransactions] = useState([])

  useEffect(() => {
    let cancelled = false
    paymentService
      .list(1)
      .then((page) => {
        if (!cancelled) setTransactions(page.results.slice(0, RECENT_COUNT))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  if (transactions.length === 0) return null

  return (
    <section className="card recent">
      <div className="card__title">
        <h2>Recent transactions</h2>
        <Link to="/transactions" className="recent__all">View all</Link>
      </div>
      <div className="txn-list">
        {transactions.map((transaction) => (
          <TransactionRow key={transaction.transaction_id} transaction={transaction} />
        ))}
      </div>
    </section>
  )
}
