import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Loads data and reloads whenever `key` changes. While reloading it keeps the
 * previous data on screen (`isLoading` tells the UI to dim it).
 */
export function useApi(fetcher, key) {
  const fetcherRef = useRef(fetcher)
  const [reloadCount, setReloadCount] = useState(0)
  const [state, setState] = useState({ requestKey: null, data: null, error: null })
  const requestKey = `${key}#${reloadCount}`

  useEffect(() => {
    fetcherRef.current = fetcher
  })

  useEffect(() => {
    let cancelled = false
    fetcherRef.current()
      .then((data) => !cancelled && setState({ requestKey, data, error: null }))
      .catch((error) => !cancelled && setState((previous) => ({ requestKey, data: previous.data, error })))
    return () => {
      cancelled = true
    }
  }, [requestKey])

  const reload = useCallback(() => setReloadCount((count) => count + 1), [])
  const isLoading = state.requestKey !== requestKey
  return { data: state.data, error: isLoading ? null : state.error, isLoading, reload }
}
