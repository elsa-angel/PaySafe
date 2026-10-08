import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Alert from '../components/Alert'
import AppShell from '../components/AppShell'
import { CheckIcon } from '../components/Icons'
import TransactionDetails from '../components/TransactionDetails'
import { paymentService } from '../services/paymentService'

export default function PaymentSuccess() {
  const { transactionId } = useParams()
  const [state, setState] = useState({ status: 'loading', transaction: null })

  useEffect(() => {
    let cancelled = false
    paymentService
      .get(transactionId)
      .then((transaction) => !cancelled && setState({ status: 'ready', transaction }))
      .catch(() => !cancelled && setState({ status: 'error', transaction: null }))
    return () => {
      cancelled = true
    }
  }, [transactionId])

  const { status, transaction } = state
  const succeeded = transaction?.status === 'COMPLETED'

  return (
    <AppShell eyebrow="Payments" title={succeeded ? 'Payment Successful' : 'Payment'}>
      <section className="card card--narrow confirmation">
        {status === 'loading' && <span className="spinner spinner--lg" role="status" aria-label="Loading" />}
        {status === 'error' && (
          <>
            <Alert>We couldn't load this payment. It may not exist, or you may need to try again.</Alert>
            <Link to="/transactions" className="btn btn--primary">View Transactions</Link>
          </>
        )}
        {status === 'ready' && (
          <>
            {succeeded && (
              <div className="confirmation__badge" aria-hidden="true"><CheckIcon width={34} height={34} strokeWidth={2.6} /></div>
            )}
            <h2>{succeeded ? 'Payment Successful' : `Payment ${transaction.status_label.toLowerCase()}`}</h2>
            <p className="confirmation__lead">
              {succeeded ? 'Your payment has been sent.' : 'See the details of this payment below.'}
            </p>
            <TransactionDetails transaction={transaction} />
            <div className="confirmation__actions">
              <Link to="/transactions" className="btn btn--primary">View Transactions</Link>
              <Link to="/payment" className="btn btn--secondary">Make Another Payment</Link>
              <Link to="/" className="confirmation__link">Back to Dashboard</Link>
            </div>
          </>
        )}
      </section>
    </AppShell>
  )
}
