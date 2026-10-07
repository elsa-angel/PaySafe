import AppShell from '../components/AppShell'
import ComingSoon from '../components/ComingSoon'

export default function Payment() {
  return (
    <AppShell eyebrow="Payments" title="Make Payment" backTo="/">
      <ComingSoon
        title="Payments are coming soon"
        message="Making payments will be available in a future update. This page marks where the payment flow will live."
      />
    </AppShell>
  )
}
