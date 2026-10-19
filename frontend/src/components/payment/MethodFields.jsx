import { BankIcon, CardIcon, LockIcon, UpiIcon, UserIcon, WalletIcon } from '../Icons'
import SelectField from '../SelectField'
import TextField from '../TextField'
import { BANKS, CARD_NETWORKS, UPI_PROVIDERS, WALLET_IDENTIFIER_TYPES, WALLETS } from '../../constants/payment'

/**
 * The extra fields for each payment method. `field(name)` supplies value, error,
 * handlers and the disabled state from the payment form. Only the selected
 * method's fields are rendered; none of them ask for PINs, passwords or OTPs.
 */

export function CardFields({ field }) {
  return (
    <>
      <TextField label="Cardholder name" required icon={UserIcon} autoComplete="off" placeholder="Name on card" {...field('cardholderName')} />
      <SelectField label="Card network" required placeholder="Select card network" options={CARD_NETWORKS} {...field('cardNetwork')} />
      <TextField label="Card number" required icon={CardIcon} inputMode="numeric" autoComplete="off" placeholder="1234 5678 9012 3456" {...field('cardNumber')} />
      <div className="field-row">
        <TextField label="Expiry date" required inputMode="numeric" autoComplete="off" placeholder="MM/YY" {...field('cardExpiry')} />
        <TextField label="CVV" required type="password" icon={LockIcon} inputMode="numeric" autoComplete="off" placeholder="123" {...field('cardCvv')} />
      </div>
    </>
  )
}

export function UpiFields({ field }) {
  return (
    <>
      <SelectField label="UPI app" required placeholder="Select UPI app" options={UPI_PROVIDERS} {...field('upiProvider')} />
      <TextField label="UPI ID (VPA)" required icon={UpiIcon} autoComplete="off" autoCapitalize="none" spellCheck={false} placeholder="name@bank" {...field('upiId')} />
    </>
  )
}

export function BankFields({ field }) {
  return (
    <>
      <SelectField label="Bank name" required placeholder="Select bank" options={BANKS} {...field('bankName')} />
      <TextField label="Account holder name" required icon={UserIcon} autoComplete="off" placeholder="Name on the account" {...field('accountHolderName')} />
      <TextField label="Bank account number" required icon={BankIcon} inputMode="numeric" autoComplete="off" placeholder="Account number" {...field('accountNumber')} />
      <TextField label="Confirm bank account number" required icon={BankIcon} inputMode="numeric" autoComplete="off" placeholder="Re-enter account number" {...field('confirmAccountNumber')} />
      <TextField label="IFSC code" required autoComplete="off" autoCapitalize="characters" spellCheck={false} placeholder="HDFC0001234" {...field('ifscCode')} />
    </>
  )
}

export function WalletFields({ field, identifierType }) {
  const isMobile = identifierType === 'MOBILE'
  return (
    <>
      <SelectField label="Wallet provider" required placeholder="Select wallet" options={WALLETS} {...field('walletProvider')} />
      <SelectField label="Identify wallet by" required placeholder="Choose one" options={WALLET_IDENTIFIER_TYPES} {...field('walletIdentifierType')} />
      <TextField
        key={identifierType}
        label={isMobile ? 'Registered mobile number' : 'Wallet ID'}
        required
        icon={isMobile ? WalletIcon : UpiIcon}
        inputMode={isMobile ? 'tel' : 'text'}
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        placeholder={isMobile ? '98765 43210' : 'name@wallet'}
        {...field('walletIdentifier')}
      />
    </>
  )
}
