import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Alert from '../components/Alert'
import AppShell from '../components/AppShell'
import Button from '../components/Button'
import { MailIcon, NoteIcon, UpiIcon, UserIcon } from '../components/Icons'
import MethodSelector from '../components/MethodSelector'
import SelectField from '../components/SelectField'
import TextField from '../components/TextField'
import { METHOD_DETAIL } from '../constants/payment'
import { createIdempotencyKey, paymentService } from '../services/paymentService'
import { requestLocation, warmUpLocation } from '../utils/geolocation'
import {
  DESCRIPTION_MAX_LENGTH,
  parseApiError,
  validateAmount,
  validateDescription,
  validateRecipientEmail,
  validateRecipientName,
  validateRequiredChoice,
  validateUpiId,
} from '../utils/validation'

const INITIAL_VALUES = {
  amount: '',
  paymentMethod: 'CARD',
  cardNetwork: '',
  upiId: '',
  bankName: '',
  walletProvider: '',
  description: '',
  recipientName: '',
  recipientEmail: '',
}

const API_FIELD_MAP = {
  amount: 'amount',
  payment_method: 'paymentMethod',
  card_network: 'cardNetwork',
  upi_id: 'upiId',
  bank_name: 'bankName',
  wallet_provider: 'walletProvider',
  description: 'description',
  recipient_name: 'recipientName',
  recipient_email: 'recipientEmail',
}

/** Validates only the fields that apply to the selected payment method. */
function validate(values) {
  const detail = METHOD_DETAIL[values.paymentMethod]
  const errors = {
    amount: validateAmount(values.amount),
    description: validateDescription(values.description),
    recipientName: validateRecipientName(values.recipientName),
    recipientEmail: validateRecipientEmail(values.recipientEmail),
  }
  errors[detail.field] =
    values.paymentMethod === 'UPI'
      ? validateUpiId(values.upiId)
      : validateRequiredChoice(values[detail.field], detail.error)
  return errors
}

export default function Payment() {
  const navigate = useNavigate()
  const [values, setValues] = useState(INITIAL_VALUES)
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const idempotencyKeyRef = useRef(createIdempotencyKey())

  // If location permission was already granted, fetch it quietly in advance (no prompt).
  useEffect(() => {
    warmUpLocation()
  }, [])

  const detail = METHOD_DETAIL[values.paymentMethod]

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

  const handleMethodChange = (paymentMethod) => {
    const previousField = METHOD_DETAIL[values.paymentMethod].field
    setValues((current) => ({ ...current, paymentMethod }))
    setErrors((current) => ({ ...current, [previousField]: '' }))
    setFormError('')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (submittingRef.current) return // blocks double-clicks before state has re-rendered

    const nextErrors = validate(values)
    setErrors(nextErrors)
    if (Object.values(nextErrors).some(Boolean)) {
      setFormError('')
      return
    }

    submittingRef.current = true
    setIsSubmitting(true)
    setFormError('')
    try {
      const location = await requestLocation() // never rejects; denial just means no coordinates
      const transaction = await paymentService.create(
        {
          amount: values.amount.trim(),
          payment_method: values.paymentMethod,
          [detail.apiField]: values[detail.field].trim(),
          description: values.description.trim(),
          recipient_name: values.recipientName.trim(),
          recipient_email: values.recipientEmail.trim(),
          latitude: location.latitude,
          longitude: location.longitude,
          location_status: location.locationStatus,
        },
        idempotencyKeyRef.current,
      )
      navigate(`/payment/success/${transaction.transaction_id}`, { replace: true })
    } catch (error) {
      // A processing failure (422) was recorded as its own transaction, so a retry needs a fresh key.
      // Network errors keep the key: if the request did arrive, the retry will not pay twice.
      if (error.status === 422) idempotencyKeyRef.current = createIdempotencyKey()
      const parsed = parseApiError(error, API_FIELD_MAP)
      setErrors(parsed.fieldErrors)
      setFormError(parsed.formError)
      submittingRef.current = false
      setIsSubmitting(false)
    }
  }

  const field = (name) => ({
    name,
    value: values[name],
    error: errors[name],
    onChange: handleChange,
    onBlur: handleBlur,
    disabled: isSubmitting,
  })

  return (
    <AppShell eyebrow="Payments" title="Make Payment" backTo="/">
      <form className="card card--narrow payment-form" onSubmit={handleSubmit} noValidate>
        <Alert>{formError}</Alert>

        <section className="form-section">
          <h2 className="form-section__title">Payment details</h2>
          <TextField
            label="Amount"
            prefix="₹"
            inputMode="decimal"
            autoComplete="off"
            placeholder="0.00"
            {...field('amount')}
          />
          <MethodSelector value={values.paymentMethod} onChange={handleMethodChange} disabled={isSubmitting} />
          <TextField
            label="Note (optional)"
            icon={NoteIcon}
            placeholder="What is this payment for?"
            maxLength={DESCRIPTION_MAX_LENGTH}
            autoComplete="off"
            {...field('description')}
          />
        </section>

        <section className="form-section">
          <h2 className="form-section__title">Recipient details</h2>
          <TextField
            label="Recipient name"
            icon={UserIcon}
            autoComplete="off"
            placeholder="Full name"
            {...field('recipientName')}
          />
          <TextField
            label="Recipient email"
            type="email"
            icon={MailIcon}
            autoComplete="off"
            placeholder="recipient@example.com"
            {...field('recipientEmail')}
          />
        </section>

        <section className="form-section">
          <h2 className="form-section__title">Payment method details</h2>
          {detail.options ? (
            <SelectField
              key={values.paymentMethod}
              label={detail.label}
              placeholder={detail.placeholder}
              options={detail.options}
              {...field(detail.field)}
            />
          ) : (
            <TextField
              key={values.paymentMethod}
              label={detail.label}
              icon={UpiIcon}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              placeholder={detail.placeholder}
              {...field(detail.field)}
            />
          )}
        </section>

        <Button type="submit" isLoading={isSubmitting} loadingText="Processing payment…">
          Continue Payment
        </Button>
      </form>
    </AppShell>
  )
}
