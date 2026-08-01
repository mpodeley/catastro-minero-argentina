import { useEffect, useState } from 'react'

// One media query the whole app reads, so the phone layout is decided in one
// place instead of by scattered magic numbers. No dependency — matchMedia is
// enough and the app ships zero CSS-in-JS.

function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
  )
  useEffect(() => {
    const mq = window.matchMedia(query)
    const on = () => setMatches(mq.matches)
    on()
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [query])
  return matches
}

/** Phone-width layout: filters fold into a sheet under the map, bigger targets. */
export const useNarrow = () => useMedia('(max-width: 640px)')
