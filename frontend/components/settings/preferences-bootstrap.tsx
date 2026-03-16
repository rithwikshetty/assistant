
import { useEffect } from 'react'
import { useTheme } from '@/components/theme-provider'
import { usePreferences } from '@/contexts/preferences-context'

export function PreferencesBootstrap() {
  const { setTheme } = useTheme()
  const { preferences } = usePreferences()

  useEffect(() => {
    if (preferences?.theme === 'light' || preferences?.theme === 'dark') {
      setTheme(preferences.theme)
    }
  }, [preferences?.theme, setTheme])

  return null
}
