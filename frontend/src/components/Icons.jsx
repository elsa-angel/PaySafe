const base = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
}

export const UserIcon = (props) => (
  <svg {...base} {...props}><circle cx="12" cy="8" r="4" /><path d="M4 20c1.5-4 4.5-6 8-6s6.5 2 8 6" /></svg>
)
export const MailIcon = (props) => (
  <svg {...base} {...props}><rect x="3" y="5" width="18" height="14" rx="3" /><path d="m4 7 8 6 8-6" /></svg>
)
export const LockIcon = (props) => (
  <svg {...base} {...props}><rect x="5" y="11" width="14" height="9" rx="3" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>
)
export const EyeIcon = (props) => (
  <svg {...base} {...props}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></svg>
)
export const EyeOffIcon = (props) => (
  <svg {...base} {...props}><path d="M3 3l18 18" /><path d="M10.6 5.1A9.7 9.7 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4M6.5 6.6C3.7 8.4 2 12 2 12s3.5 7 10 7c1.7 0 3.2-.4 4.5-1" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /></svg>
)
export const CheckIcon = (props) => (
  <svg {...base} {...props}><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
)
export const AlertIcon = (props) => (
  <svg {...base} {...props}><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5M12 16.2v.1" /></svg>
)
export const ShieldIcon = (props) => (
  <svg {...base} {...props}><path d="M12 3 5 6v5.5c0 4.2 2.9 7.6 7 9.5 4.1-1.9 7-5.3 7-9.5V6l-7-3Z" /><path d="m9 12 2.2 2.2L15.2 10" /></svg>
)
export const ActivityIcon = (props) => (
  <svg {...base} {...props}><path d="M3 12h4l2.5-6 5 12 2.5-6H21" /></svg>
)
export const LogoutIcon = (props) => (
  <svg {...base} {...props}><path d="M9 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h3" /><path d="M16 8l4 4-4 4M20 12H9" /></svg>
)
export const SendIcon = (props) => (
  <svg {...base} {...props}><path d="M21 3 10 14" /><path d="m21 3-7 18-4-7-7-4 18-7Z" /></svg>
)
export const ListIcon = (props) => (
  <svg {...base} {...props}><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" /><circle cx="4.5" cy="18" r="1" /></svg>
)
export const ChevronDownIcon = (props) => (
  <svg {...base} {...props}><path d="m6 9 6 6 6-6" /></svg>
)
export const ArrowRightIcon = (props) => (
  <svg {...base} {...props}><path d="M5 12h14M13 6l6 6-6 6" /></svg>
)
export const ArrowLeftIcon = (props) => (
  <svg {...base} {...props}><path d="M19 12H5M11 6l-6 6 6 6" /></svg>
)
export const ClockIcon = (props) => (
  <svg {...base} {...props}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
)
export const CardIcon = (props) => (
  <svg {...base} {...props}><rect x="3" y="5" width="18" height="14" rx="3" /><path d="M3 10h18M7 15h4" /></svg>
)
export const UpiIcon = (props) => (
  <svg {...base} {...props}><circle cx="12" cy="12" r="4" /><path d="M16 12v1.5a2.5 2.5 0 0 0 5 0V12a9 9 0 1 0-3.5 7.1" /></svg>
)
export const BankIcon = (props) => (
  <svg {...base} {...props}><path d="m3 9 9-5 9 5H3ZM5 9v8M9.7 9v8M14.3 9v8M19 9v8M3 20h18" /></svg>
)
export const WalletIcon = (props) => (
  <svg {...base} {...props}><path d="M19 8V6a2 2 0 0 0-2-2H6a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h13a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2H6" /><circle cx="16.5" cy="13.5" r="1" /></svg>
)
export const NoteIcon = (props) => (
  <svg {...base} {...props}><path d="M6 3h9l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" /><path d="M14 3v5h5M8.5 13h7M8.5 17h5" /></svg>
)
export const ReceiptIcon = (props) => (
  <svg {...base} {...props}><path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z" /><path d="M9 8h6M9 12h6" /></svg>
)
export const SearchIcon = (props) => (
  <svg {...base} {...props}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
)
export const DownloadIcon = (props) => (
  <svg {...base} {...props}><path d="M12 4v11M7 11l5 5 5-5M5 20h14" /></svg>
)
