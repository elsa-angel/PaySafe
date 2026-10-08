import { Route, Routes } from 'react-router-dom'
import { ProtectedRoute, PublicOnlyRoute } from './components/ProtectedRoute'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import Payment from './pages/Payment'
import PaymentSuccess from './pages/PaymentSuccess'
import Profile from './pages/Profile'
import Signup from './pages/Signup'
import TransactionDetail from './pages/TransactionDetail'
import Transactions from './pages/Transactions'

export default function App() {
  return (
    <Routes>
      <Route element={<PublicOnlyRoute />}>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
      </Route>
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/payment" element={<Payment />} />
        <Route path="/payment/success/:transactionId" element={<PaymentSuccess />} />
        <Route path="/transactions" element={<Transactions />} />
        <Route path="/transactions/:transactionId" element={<TransactionDetail />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
