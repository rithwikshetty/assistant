import * as React from "react"

const MOBILE_BREAKPOINT = 600

export function useIsMobile() {
  // Start with false to match SSR output and avoid hydration mismatches.
  // The actual value is determined client-side after mount via useEffect.
  const [isMobile, setIsMobile] = React.useState(false)

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    }
    mql.addEventListener("change", onChange)
    // Set initial value based on actual window width after hydration
    setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return isMobile
}
