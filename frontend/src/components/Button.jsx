export default function Button({ children, isLoading = false, loadingText, variant = 'primary', disabled, ...props }) {
  return (
    <button
      className={`btn btn--${variant}`}
      disabled={disabled || isLoading}
      aria-busy={isLoading}
      {...props}
    >
      {isLoading && <span className="spinner" aria-hidden="true" />}
      <span>{isLoading && loadingText ? loadingText : children}</span>
    </button>
  )
}
