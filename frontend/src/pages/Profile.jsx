import { useState } from 'react'
import Alert from '../components/Alert'
import AppShell from '../components/AppShell'
import Button from '../components/Button'
import { LockIcon, MailIcon, ShieldIcon, UserIcon } from '../components/Icons'
import TextField from '../components/TextField'
import { useAuth } from '../context/useAuth'
import { authService } from '../services/authService'
import {
  parseApiError,
  passwordChecks,
  validateConfirmPassword,
  validateCurrentPassword,
  validateFullName,
  validateNewPassword,
} from '../utils/validation'

function ProfileDetails() {
  const { user, updateProfile } = useAuth()
  const [isEditing, setIsEditing] = useState(false)
  const [fullName, setFullName] = useState(user.full_name)
  const [error, setError] = useState('')
  const [formError, setFormError] = useState('')
  const [success, setSuccess] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  const startEditing = () => {
    setFullName(user.full_name)
    setError('')
    setFormError('')
    setSuccess('')
    setIsEditing(true)
  }

  const cancelEditing = () => {
    setIsEditing(false)
    setError('')
    setFormError('')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (isSaving) return

    const validationError = validateFullName(fullName)
    setError(validationError)
    if (validationError) return

    setIsSaving(true)
    setFormError('')
    try {
      await updateProfile({ fullName: fullName.trim() })
      setSuccess('Your profile has been updated.')
      setIsEditing(false)
    } catch (apiError) {
      const parsed = parseApiError(apiError, { full_name: 'fullName' })
      setError(parsed.fieldErrors.fullName || '')
      setFormError(parsed.formError)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <section className="card">
      <div className="card__title">
        <UserIcon /> <h2>Profile details</h2>
      </div>

      {success && !isEditing && <Alert variant="success">{success}</Alert>}

      {isEditing ? (
        <form className="form" onSubmit={handleSubmit} noValidate>
          <Alert>{formError}</Alert>
          <TextField
            label="Full name"
            name="fullName"
            icon={UserIcon}
            autoComplete="name"
            value={fullName}
            error={error}
            onChange={(event) => {
              setFullName(event.target.value)
              setError('')
              setFormError('')
            }}
            disabled={isSaving}
            autoFocus
          />
          <TextField
            label="Email"
            name="email"
            icon={MailIcon}
            value={user.email}
            hint="Your email can't be changed."
            readOnly
            disabled
          />
          <div className="form-actions">
            <Button type="button" variant="secondary" onClick={cancelEditing} disabled={isSaving}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isSaving} loadingText="Saving…">
              Save Changes
            </Button>
          </div>
        </form>
      ) : (
        <>
          <dl className="details">
            <div><dt>Full name</dt><dd>{user.full_name}</dd></div>
            <div><dt>Email</dt><dd>{user.email}</dd></div>
          </dl>
          <div className="form-actions form-actions--start">
            <Button type="button" onClick={startEditing}>Edit Profile</Button>
          </div>
        </>
      )}
    </section>
  )
}

const EMPTY_PASSWORDS = { currentPassword: '', newPassword: '', confirmNewPassword: '' }

const PASSWORD_FIELD_MAP = {
  current_password: 'currentPassword',
  new_password: 'newPassword',
  confirm_new_password: 'confirmNewPassword',
}

function ChangePassword() {
  const [values, setValues] = useState(EMPTY_PASSWORDS)
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [success, setSuccess] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  const validate = (current) => ({
    currentPassword: validateCurrentPassword(current.currentPassword),
    newPassword: validateNewPassword(current.newPassword),
    confirmNewPassword: validateConfirmPassword(current.newPassword, current.confirmNewPassword),
  })

  const handleChange = (event) => {
    const { name, value } = event.target
    setValues((current) => ({ ...current, [name]: value }))
    setErrors((current) => ({ ...current, [name]: '' }))
    setFormError('')
    setSuccess('')
  }

  const handleBlur = (event) => {
    const { name } = event.target
    if (!values[name] || name === 'currentPassword') return
    setErrors((current) => ({ ...current, [name]: validate(values)[name] }))
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (isSaving) return

    const nextErrors = validate(values)
    setErrors(nextErrors)
    setSuccess('')
    if (Object.values(nextErrors).some(Boolean)) return

    setIsSaving(true)
    setFormError('')
    try {
      await authService.changePassword(values)
      setValues(EMPTY_PASSWORDS)
      setErrors({})
      setSuccess('Your password has been updated.')
    } catch (apiError) {
      const parsed = parseApiError(apiError, PASSWORD_FIELD_MAP)
      setErrors(parsed.fieldErrors)
      setFormError(parsed.formError)
    } finally {
      setIsSaving(false)
    }
  }

  const checks = passwordChecks(values.newPassword)

  return (
    <section className="card">
      <div className="card__title">
        <ShieldIcon /> <h2>Change password</h2>
      </div>
      <form className="form" onSubmit={handleSubmit} noValidate>
        <Alert variant="success">{success}</Alert>
        <Alert>{formError}</Alert>
        <TextField
          label="Current password"
          name="currentPassword"
          type="password"
          icon={LockIcon}
          autoComplete="current-password"
          value={values.currentPassword}
          error={errors.currentPassword}
          onChange={handleChange}
          disabled={isSaving}
        />
        <TextField
          label="New password"
          name="newPassword"
          type="password"
          icon={LockIcon}
          autoComplete="new-password"
          value={values.newPassword}
          error={errors.newPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          disabled={isSaving}
        />
        {values.newPassword && (
          <ul className="checklist" aria-label="Password requirements">
            {checks.map((check) => (
              <li key={check.id} className={check.met ? 'is-met' : ''}>
                {check.label}
              </li>
            ))}
          </ul>
        )}
        <TextField
          label="Confirm new password"
          name="confirmNewPassword"
          type="password"
          icon={LockIcon}
          autoComplete="new-password"
          value={values.confirmNewPassword}
          error={errors.confirmNewPassword}
          onChange={handleChange}
          onBlur={handleBlur}
          disabled={isSaving}
        />
        <div className="form-actions form-actions--start">
          <Button type="submit" isLoading={isSaving} loadingText="Updating…">
            Update password
          </Button>
        </div>
      </form>
    </section>
  )
}

export default function Profile() {
  return (
    <AppShell eyebrow="Account" title="Profile" backTo="/">
      <div className="stack">
        <ProfileDetails />
        <ChangePassword />
      </div>
    </AppShell>
  )
}
