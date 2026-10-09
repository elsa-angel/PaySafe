import { Route, Routes } from 'react-router-dom'
import { ProtectedRoute, PublicOnlyRoute, RoleRoute } from './components/ProtectedRoute'
import AdminFraud from './pages/admin/AdminFraud'
import AdminOverview from './pages/admin/AdminOverview'
import AdminReports from './pages/admin/AdminReports'
import AdminTransactionDetail from './pages/admin/AdminTransactionDetail'
import AdminTransactions from './pages/admin/AdminTransactions'
import AdminUserDetail from './pages/admin/AdminUserDetail'
import AdminUsers from './pages/admin/AdminUsers'
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
        <Route path="/profile" element={<Profile />} />

        <Route element={<RoleRoute role="user" />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/payment" element={<Payment />} />
          <Route path="/payment/success/:transactionId" element={<PaymentSuccess />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/transactions/:transactionId" element={<TransactionDetail />} />
        </Route>

        <Route element={<RoleRoute role="admin" />}>
          <Route path="/admin" element={<AdminOverview />} />
          <Route path="/admin/fraud" element={<AdminFraud />} />
          <Route path="/admin/users" element={<AdminUsers />} />
          <Route path="/admin/users/:userId" element={<AdminUserDetail />} />
          <Route path="/admin/transactions" element={<AdminTransactions />} />
          <Route path="/admin/transactions/:transactionId" element={<AdminTransactionDetail />} />
          <Route path="/admin/reports" element={<AdminReports />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
