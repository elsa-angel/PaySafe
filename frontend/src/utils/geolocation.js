/**
 * Optional browser location for payments. Never rejects: a denied or
 * unavailable location simply resolves to null coordinates, so a payment is
 * never blocked by it. The browser only prompts the first time; a denial is
 * remembered for the page session so we don't ask again.
 */
const GRANTED_MAX_AGE_MS = 5 * 60 * 1000
const LOCATION_TIMEOUT_MS = 8000

let cached = null // { latitude, longitude, locationStatus, at }
let inFlight = null

const empty = (locationStatus) => ({ latitude: null, longitude: null, locationStatus })

function isFresh(entry) {
  if (!entry) return false
  return entry.locationStatus === 'DENIED' || Date.now() - entry.at < GRANTED_MAX_AGE_MS
}

export function requestLocation() {
  if (isFresh(cached)) return Promise.resolve(cached)
  if (inFlight) return inFlight

  inFlight = new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
      resolve(empty('UNAVAILABLE'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) =>
        resolve({ latitude: coords.latitude, longitude: coords.longitude, locationStatus: 'PROVIDED' }),
      (error) => resolve(empty(error.code === error.PERMISSION_DENIED ? 'DENIED' : 'UNAVAILABLE')),
      { enableHighAccuracy: false, timeout: LOCATION_TIMEOUT_MS, maximumAge: GRANTED_MAX_AGE_MS },
    )
  }).then((result) => {
    // Only remember outcomes that won't change on their own (success or denial).
    cached = result.locationStatus === 'UNAVAILABLE' ? null : { ...result, at: Date.now() }
    inFlight = null
    return result
  })
  return inFlight
}

/** Silently fetches location ahead of time, but only if permission is already granted (no prompt). */
export async function warmUpLocation() {
  try {
    const status = await navigator.permissions?.query({ name: 'geolocation' })
    if (status?.state === 'granted') await requestLocation()
  } catch {
    // Permissions API unsupported: location will be requested on submit instead.
  }
}
