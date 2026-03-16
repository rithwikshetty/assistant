import { fetchWithAuth } from '@/lib/api/auth'
import type { ApiSchema } from '@/lib/api/generated/types'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'

const API_BASE_URL = getBackendBaseUrl()

export type PreferencesResponse = ApiSchema<"PreferencesResponse">
export type PreferencesUpdatePayload = ApiSchema<"PreferencesUpdate">
export type Theme = NonNullable<PreferencesResponse["theme"]>

export async function getPreferences(): Promise<PreferencesResponse | null> {
  const res = await fetchWithAuth(`${API_BASE_URL}/users/me/preferences`, { cache: 'no-store' })
  if (!res.ok) return null
  return res.json()
}

export async function updatePreferences(payload: PreferencesUpdatePayload): Promise<PreferencesResponse | null> {
  const res = await fetchWithAuth(`${API_BASE_URL}/users/me/preferences`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) return null
  return res.json()
}
