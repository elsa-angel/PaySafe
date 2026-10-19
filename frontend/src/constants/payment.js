import { BankIcon, CardIcon, UpiIcon, WalletIcon } from '../components/Icons'

// Values mirror the Django choices in payments/models.py (the backend validates them).
export const PAYMENT_METHODS = [
  { value: 'CARD', label: 'Card', icon: CardIcon },
  { value: 'UPI', label: 'UPI', icon: UpiIcon },
  { value: 'BANK_TRANSFER', label: 'Bank Transfer', icon: BankIcon },
  { value: 'WALLET', label: 'Wallet', icon: WalletIcon },
]

export const METHOD_ICONS = Object.fromEntries(PAYMENT_METHODS.map(({ value, icon }) => [value, icon]))

export const CARD_NETWORKS = [
  { value: 'VISA', label: 'Visa' },
  { value: 'MASTERCARD', label: 'Mastercard' },
  { value: 'RUPAY', label: 'RuPay' },
  { value: 'OTHER', label: 'Other' },
]

export const BANKS = [
  { value: 'SBI', label: 'State Bank of India' },
  { value: 'HDFC', label: 'HDFC Bank' },
  { value: 'ICICI', label: 'ICICI Bank' },
  { value: 'AXIS', label: 'Axis Bank' },
  { value: 'KOTAK', label: 'Kotak Mahindra Bank' },
  { value: 'PNB', label: 'Punjab National Bank' },
  { value: 'BOB', label: 'Bank of Baroda' },
  { value: 'CANARA', label: 'Canara Bank' },
  { value: 'OTHER', label: 'Other' },
]

export const WALLETS = [
  { value: 'PAYTM', label: 'Paytm' },
  { value: 'PHONEPE', label: 'PhonePe' },
  { value: 'GOOGLE_PAY', label: 'Google Pay' },
  { value: 'AMAZON_PAY', label: 'Amazon Pay' },
  { value: 'OTHER', label: 'Other' },
]

export const UPI_PROVIDERS = [
  { value: 'GOOGLE_PAY', label: 'Google Pay' },
  { value: 'PHONEPE', label: 'PhonePe' },
  { value: 'PAYTM', label: 'Paytm' },
  { value: 'BHIM', label: 'BHIM' },
  { value: 'AMAZON_PAY', label: 'Amazon Pay' },
  { value: 'OTHER', label: 'Other' },
]

export const WALLET_IDENTIFIER_TYPES = [
  { value: 'MOBILE', label: 'Registered mobile number' },
  { value: 'WALLET_ID', label: 'Wallet ID' },
]

/** The first four letters of an IFSC identify the bank (mirrors the backend). */
export const IFSC_BANK_PREFIX = {
  SBI: 'SBIN', HDFC: 'HDFC', ICICI: 'ICIC', AXIS: 'UTIB',
  KOTAK: 'KKBK', PNB: 'PUNB', BOB: 'BARB', CANARA: 'CNRB',
}
