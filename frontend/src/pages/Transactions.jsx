import AppShell from '../components/AppShell'
import ComingSoon from '../components/ComingSoon'

export default function Transactions() {
  return (
    <AppShell eyebrow="Activity" title="Transactions" backTo="/">
      <ComingSoon
        title="Transactions are coming soon"
        message="Your transaction activity will appear here in a future update."
      />
    </AppShell>
  )
}
