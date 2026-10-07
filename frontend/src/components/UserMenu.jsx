import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { ChevronDownIcon, LogoutIcon, UserIcon } from './Icons'

const getInitials = (name) =>
  name.split(' ').filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join('')

/** Avatar + name in the header; opens a small menu with Profile and Sign out. */
export default function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const handlePointer = (event) => {
      if (!menuRef.current?.contains(event.target)) setOpen(false)
    }
    const handleKey = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  const handleLogout = async () => {
    setIsLoggingOut(true)
    try {
      await logout()
    } catch {
      setIsLoggingOut(false)
    }
  }

  return (
    <div className="user-menu" ref={menuRef}>
      <button
        type="button"
        className="user-menu__trigger"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="avatar" aria-hidden="true">{getInitials(user.full_name)}</span>
        <span className="user-menu__name">{user.full_name}</span>
        <ChevronDownIcon width={16} height={16} aria-hidden="true" />
      </button>

      {open && (
        <div className="user-menu__panel" role="menu">
          <div className="user-menu__who">
            <strong>{user.full_name}</strong>
            <span>{user.email}</span>
          </div>
          <Link to="/profile" role="menuitem" className="user-menu__item" onClick={() => setOpen(false)}>
            <UserIcon width={18} height={18} /> Profile
          </Link>
          <button
            type="button"
            role="menuitem"
            className="user-menu__item"
            onClick={handleLogout}
            disabled={isLoggingOut}
          >
            <LogoutIcon width={18} height={18} /> {isLoggingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      )}
    </div>
  )
}
