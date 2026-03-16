import { fetchWithAuth } from '@/lib/api/auth'
import type { ApiSchema } from '@/lib/api/generated/types'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'

const API_BASE_URL = getBackendBaseUrl()

export type RedactionEntry = ApiSchema<"RedactionEntryResponse">
export type RedactionEntryCreate = ApiSchema<"RedactionEntryCreate">
export type RedactionEntryUpdate = ApiSchema<"RedactionEntryUpdate">

export async function getRedactionList(): Promise<RedactionEntry[]> {
  const res = await fetchWithAuth(`${API_BASE_URL}/users/me/redaction-list`, {
    cache: 'no-store',
  })
  if (!res.ok) {
    throw new Error('Failed to fetch redaction list')
  }
  return res.json()
}

export async function addRedactionEntry(
  payload: RedactionEntryCreate
): Promise<RedactionEntry> {
  const res = await fetchWithAuth(`${API_BASE_URL}/users/me/redaction-list`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    throw new Error('Failed to add redaction entry')
  }
  return res.json()
}

export async function updateRedactionEntry(
  id: string,
  payload: RedactionEntryUpdate
): Promise<RedactionEntry> {
  const res = await fetchWithAuth(
    `${API_BASE_URL}/users/me/redaction-list/${id}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }
  )
  if (!res.ok) {
    throw new Error('Failed to update redaction entry')
  }
  return res.json()
}

export async function deleteRedactionEntry(id: string): Promise<void> {
  const res = await fetchWithAuth(
    `${API_BASE_URL}/users/me/redaction-list/${id}`,
    {
      method: 'DELETE',
    }
  )
  if (!res.ok) {
    throw new Error('Failed to delete redaction entry')
  }
}
