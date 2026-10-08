import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Alert from '../components/Alert'
import AppShell from '../components/AppShell'
import Button from '../components/Button'
import { ReceiptIcon } from '../components/Icons'
import TransactionRow from '../components/TransactionRow'
import { paymentService } from '../services/paymentService'

export default function Transactions() {
  const [transactions, setTransactions] = useState([])
  const [nextPage, setNextPage] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ready | error
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState(false)

  const applyFirstPage = useCallback((page) => {
    setTransactions(page.results)
    setNextPage(page.next ? 2 : null)
    setStatus('ready')
  }, [])

  useEffect(() => {
    let cancelled = false
    paymentService
      .list(1)
      .then((page) => !cancelled && applyFirstPage(page))
      .catch(() => !cancelled && setStatus('error'))
    return () => {
      cancelled = true
    }
  }, [applyFirstPage])

  const retry = () => {
    setStatus('loading')
    paymentService.list(1).then(applyFirstPage).catch(() => setStatus('error'))
  }

  const loadMore = async () => {
    setIsLoadingMore(true)
    setLoadMoreError(false)
    try {
      const page = await paymentService.list(nextPage)
      setTransactions((current) => [...current, ...page.results])
      setNextPage(page.next ? nextPage + 1 : null)
    } catch {
      setLoadMoreError(true)
    } finally {
      setIsLoadingMore(false)
    }
  }

  return (
    <AppShell eyebrow="Activity" title="Transactions" backTo="/">
      {status === 'loading' && (
        <section className="card empty-state">
          <span className="spinner spinner--lg" role="status" aria-label="Loading transactions" />
        </section>
      )}

      {status === 'error' && (
        <section className="card empty-state">
          <Alert>We couldn't load your transactions.</Alert>
          <Button type="button" onClick={retry}>Try again</Button>
        </section>
      )}

      {status === 'ready' && transactions.length === 0 && (
        <section className="card empty-state">
          <span className="empty-state__icon"><ReceiptIcon width={28} height={28} /></span>
          <h2>No transactions yet</h2>
          <p>Payments you make will show up here.</p>
          <Link to="/payment" className="btn btn--primary">Make a payment</Link>
        </section>
      )}

      {status === 'ready' && transactions.length > 0 && (
        <section className="card card--list">
          <div className="txn-list">
            {transactions.map((transaction) => (
              <TransactionRow key={transaction.transaction_id} transaction={transaction} />
            ))}
          </div>
          {loadMoreError && <Alert>We couldn't load more transactions.</Alert>}
          {nextPage && (
            <div className="txn-more">
              <Button type="button" variant="secondary" onClick={loadMore} isLoading={isLoadingMore} loadingText="Loading…">
                Load more
              </Button>
            </div>
          )}
        </section>
      )}
    </AppShell>
  )
}
