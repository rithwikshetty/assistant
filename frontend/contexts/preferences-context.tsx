/* @refresh skip */

/* @refresh skip */
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  getPreferences,
  updatePreferences as updatePreferencesApi,
  PreferencesResponse,
  PreferencesUpdatePayload,
  Theme,
} from '@/lib/api/preferences'
import { useAuth } from '@/contexts/auth-context'

interface PreferencesContextType {
  preferences: PreferencesResponse | null
  loading: boolean
  error: string | null
  updateTheme: (theme: Theme) => Promise<void>
  updatePreferences: (payload: PreferencesUpdatePayload) => Promise<void>
  refresh: () => Promise<void>
}

const PreferencesContext = createContext<PreferencesContextType | undefined>(undefined)

interface PreferencesProviderProps {
  children: ReactNode
}

export function PreferencesProvider({ children }: PreferencesProviderProps) {
  const { isBackendAuthenticated } = useAuth()
  const [preferences, setPreferences] = useState<PreferencesResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchPreferences = useCallback(async () => {
    if (!isBackendAuthenticated) {
      setPreferences(null)
      return
    }

    setLoading(true)
    setError(null)
    try {
      const prefs = await getPreferences()
      setPreferences(prefs)
    } catch (_err) {
      setError('Failed to load preferences')
      // Error fetching preferences
    } finally {
      setLoading(false)
    }
  }, [isBackendAuthenticated])

  const updateTheme = async (theme: Theme) => {
    try {
      const updated = await updatePreferencesApi({ theme })
      if (updated) {
        setPreferences(updated)
      }
    } catch (_err) {
      setError('Failed to update theme')
      // Error updating theme
    }
  }

  const updatePreferences = async (payload: PreferencesUpdatePayload) => {
    try {
      const updated = await updatePreferencesApi(payload)
      if (updated) {
        setPreferences(updated)
      }
    } catch (_err) {
      setError('Failed to update preferences')
    }
  }

  useEffect(() => {
    fetchPreferences()
  }, [fetchPreferences])

  const value: PreferencesContextType = {
    preferences,
    loading,
    error,
    updateTheme,
    updatePreferences,
    refresh: fetchPreferences,
  }

  return (
    <PreferencesContext.Provider value={value}>
      {children}
    </PreferencesContext.Provider>
  )
}

export function usePreferences(): PreferencesContextType {
  const context = useContext(PreferencesContext)
  if (context === undefined) {
    throw new Error('usePreferences must be used within a PreferencesProvider')
  }
  return context
}
