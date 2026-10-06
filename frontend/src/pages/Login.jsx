import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import Alert from '../components/Alert'
import AuthLayout from '../components/AuthLayout'
import Button from '../components/Button'
import { LockIcon, MailIcon } from '../components/Icons'
import TextField from '../components/TextField'
import { useAuth } from '../context/useAuth'
import { parseApiError, validateEmail, validateLoginPassword } from '../utils/validation'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const justRegistered = Boolean(location.state?.registered)
  const redirectTo = location.state?.from?.pathname || '/'

  const [values, setValues] = useState({ email: location.state?.email ?? '', password: '' })
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const validate = (current) => ({
    email: validateEmail(current.email),
    password: validateLoginPassword(current.password),
  })

  const handleChange = (event) => {
    const { name, value } = event.target
    setValues((current) => ({ ...current, [name]: value }))
    setErrors((current) => ({ ...current, [name]: '' }))
    setFormError('')
  }

  const handleBlur = (event) => {
    const { name } = event.target
    if (name === 'email' && values.email) {
      setErrors((current) => ({ ...current, email: validate(values).email }))
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (isSubmitting) return

    const nextErrors = validate(values)
    setErrors(nextErrors)
    if (Object.values(nextErrors).some(Boolean)) return

    setIsSubmitting(true)
    setFormError('')
    try {
      await login({ email: values.email.trim(), password: values.password })
      navigate(redirectTo, { replace: true })
    } catch (error) {
      const parsed = parseApiError(error, { email: 'email', password: 'password' })
      setErrors(parsed.fieldErrors)
      setFormError(parsed.formError)
      setIsSubmitting(false)
    }
  }

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to continue to your PaySafe account."
      footer={<>New to PaySafe? <Link to="/signup">Create an account</Link></>}
    >
      <form className="form" onSubmit={handleSubmit} noValidate>
        {justRegistered && !formError && (
          <Alert variant="success">Account created successfully. Sign in to get started.</Alert>
        )}
        <Alert>{formError}</Alert>

        <TextField
          label="Email"
          name="email"
          type="email"
          icon={MailIcon}
          autoComplete="email"
          placeholder="you@example.com"
          value={values.email}
          error={errors.email}
          onChange={handleChange}
          onBlur={handleBlur}
          disabled={isSubmitting}
        />
        <TextField
          label="Password"
          name="password"
          type="password"
          icon={LockIcon}
          autoComplete="current-password"
          placeholder="Enter your password"
          value={values.password}
          error={errors.password}
          onChange={handleChange}
          disabled={isSubmitting}
        />

        <Button type="submit" isLoading={isSubmitting} loadingText="Signing in…">
          Sign in
        </Button>
      </form>
    </AuthLayout>
  )
}
