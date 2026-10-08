import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import AppShell from '../components/AppShell'
import { ReceiptIcon } from '../components/Icons'
import TransactionDetails from '../components/TransactionDetails'
import { paymentService } from '../services/paymentService'

export default function TransactionDetail() {
  const { transactionId } = useParams()
  const [state, setState] = useState({ status: 'loading', transaction: null })

  useEffect(() => {
    let cancelled = false
    paymentService
      .get(transactionId)
      .then((transaction) => !cancelled && setState({ status: 'ready', transaction }))
      .catch((error) => !cancelled && setState({ status: error.status === 404 ? 'missing' : 'error', transaction: null }))
    return () => {
      cancelled = true
    }
  }, [transactionId])

  const { status, transaction } = state

  return (
    <AppShell eyebrow="Transaction" title="Transaction details" backTo="/transactions" backLabel="Transactions">
      <section className="card card--narrow">
        {status === 'loading' && (
          <div className="empty-state"><span className="spinner spinner--lg" role="status" aria-label="Loading" /></div>
        )}
        {(status === 'missing' || status === 'error') && (
          <div className="empty-state">
            <span className="empty-state__icon"><ReceiptIcon width={28} height={28} /></span>
            <h2>{status === 'missing' ? 'Transaction not found' : "We couldn't load this transaction"}</h2>
            <p>{status === 'missing' ? "It doesn't exist, or it isn't one of your transactions." : 'Please try again in a moment.'}</p>
            <Link to="/transactions" className="btn btn--primary">Back to transactions</Link>
          </div>
        )}
        {status === 'ready' && <TransactionDetails transaction={transaction} />}
      </section>
    </AppShell>
  )
}
