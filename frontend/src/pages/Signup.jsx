import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Alert from '../components/Alert'
import AuthLayout from '../components/AuthLayout'
import Button from '../components/Button'
import { CheckIcon, LockIcon, MailIcon, UserIcon } from '../components/Icons'
import TextField from '../components/TextField'
import { authService } from '../services/authService'
import {
  parseApiError,
  passwordChecks,
  validateConfirmPassword,
  validateEmail,
  validateFullName,
  validateNewPassword,
} from '../utils/validation'

const INITIAL_VALUES = { fullName: '', email: '', password: '', confirmPassword: '' }

const API_FIELD_MAP = {
  full_name: 'fullName',
  email: 'email',
  password: 'password',
  confirm_password: 'confirmPassword',
}

function validate(values) {
  return {
    fullName: validateFullName(values.fullName),
    email: validateEmail(values.email),
    password: validateNewPassword(values.password),
    confirmPassword: validateConfirmPassword(values.password, values.confirmPassword),
  }
}

export default function Signup() {
  const navigate = useNavigate()
  const [values, setValues] = useState(INITIAL_VALUES)
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleChange = (event) => {
    const { name, value } = event.target
    setValues((current) => ({ ...current, [name]: value }))
    setErrors((current) => ({ ...current, [name]: '' }))
    setFormError('')
  }

  const handleBlur = (event) => {
    const { name } = event.target
    if (!values[name]) return
    setErrors((current) => ({ ...current, [name]: validate(values)[name] }))
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (isSubmitting) return

    const nextErrors = validate(values)
    setErrors(nextErrors)
    if (Object.values(nextErrors).some(Boolean)) {
      setFormError('')
      return
    }

    setIsSubmitting(true)
    setFormError('')
    try {
      const user = await authService.signup({
        ...values,
        fullName: values.fullName.trim(),
        email: values.email.trim(),
      })
      navigate('/login', { replace: true, state: { registered: true, email: user.email } })
    } catch (error) {
      const parsed = parseApiError(error, API_FIELD_MAP)
      setErrors(parsed.fieldErrors)
      setFormError(parsed.formError)
      setIsSubmitting(false)
    }
  }

  const checks = passwordChecks(values.password)

  return (
    <AuthLayout
      title="Create account"
      subtitle="Start sending and receiving payments securely."
      footer={<>Already have an account? <Link to="/login">Sign in</Link></>}
    >
      <form className="form" onSubmit={handleSubmit} noValidate>
        <Alert>{formError}</Alert>

        <TextField
          label="Full name"
          name="fullName"
          icon={UserIcon}
          autoComplete="name"
          placeholder="Jane Cooper"
          value={values.fullName}
          error={errors.fullName}
          onChange={handleChange}
          onBlur={handleBlur}
          disabled={isSubmitting}
        />
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
          autoComplete="new-password"
          placeholder="Create a password"
          value={values.password}
          error={errors.password}
          onChange={handleChange}
          onBlur={handleBlur}
          disabled={isSubmitting}
        />
        {values.password && (
          <ul className="checklist" aria-label="Password requirements">
            {checks.map((check) => (
              <li key={check.id} className={check.met ? 'is-met' : ''}>
                <CheckIcon width={14} height={14} /> {check.label}
              </li>
            ))}
          </ul>
        )}
        <TextField
          label="Confirm password"
          name="confirmPassword"
          type="password"
          icon={LockIcon}
          autoComplete="new-password"
          placeholder="Repeat your password"
          value={values.confirmPassword}
          error={errors.confirmPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          disabled={isSubmitting}
        />

        <Button type="submit" isLoading={isSubmitting} loadingText="Creating account…">
          Create account
        </Button>
      </form>
    </AuthLayout>
  )
}
