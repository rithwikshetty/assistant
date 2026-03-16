import { fetchWithAuth } from '@/lib/api/auth'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'

const API_BASE_URL = getBackendBaseUrl()

export type Role = 'user' | 'admin'
export type Tier = 'default' | 'power'

export interface UserAdmin {
  id: string
  email: string
  name?: string | null
  role: Role
  user_tier: Tier
  model_override?: string | null
  is_active: boolean
  created_at: string
  last_login_at?: string | null
  conversation_count: number
  total_cost_usd: number
}

export interface UsersPage {
  total: number
  page: number
  page_size: number
  items: UserAdmin[]
}

export interface UserLookupItem {
  id: string
  email: string
  name?: string | null
  role: Role
}

export async function listUsers(params: {
  search?: string
  include_admins?: boolean
  page?: number
  page_size?: number
  sort_by?: string
  sort_dir?: string
}): Promise<UsersPage> {
  const searchParams = new URLSearchParams()
  if (params.search) searchParams.set('search', params.search)
  if (typeof params.include_admins === 'boolean') searchParams.set('include_admins', String(params.include_admins))
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.sort_by) searchParams.set('sort_by', params.sort_by)
  if (params.sort_dir) searchParams.set('sort_dir', params.sort_dir)

  const res = await fetchWithAuth(`${API_BASE_URL}/admin/users?${searchParams.toString()}`, {
    method: 'GET',
    cache: 'no-store',
  })
  if (!res.ok) {
    throw new Error(`Failed to fetch users (${res.status})`)
  }
  return res.json()
}

export async function setUserRole(userId: string, role: Role): Promise<UserAdmin> {
  const res = await fetchWithAuth(`${API_BASE_URL}/admin/users/${userId}/role`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err?.detail || `Failed to update role (${res.status})`)
  }
  return res.json()
}

export async function setUserActive(userId: string, isActive: boolean): Promise<UserAdmin> {
  const res = await fetchWithAuth(`${API_BASE_URL}/admin/users/${userId}/active`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_active: isActive }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err?.detail || `Failed to update access (${res.status})`)
  }
  return res.json()
}

export async function setUserTier(userId: string, tier: Tier): Promise<UserAdmin> {
  const res = await fetchWithAuth(`${API_BASE_URL}/admin/users/${userId}/tier`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err?.detail || `Failed to update tier (${res.status})`)
  }
  return res.json()
}

export async function setUserModel(userId: string, model: string | null): Promise<UserAdmin> {
  const res = await fetchWithAuth(`${API_BASE_URL}/admin/users/${userId}/model`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err?.detail || `Failed to update model override (${res.status})`)
  }
  return res.json()
}

export async function lookupUsers(params: {
  search: string
  include_admins?: boolean
  limit?: number
}): Promise<{ items: UserLookupItem[] }> {
  const searchParams = new URLSearchParams()
  searchParams.set('search', params.search)
  if (typeof params.include_admins === 'boolean') searchParams.set('include_admins', String(params.include_admins))
  if (params.limit) searchParams.set('limit', String(params.limit))

  const res = await fetchWithAuth(`${API_BASE_URL}/admin/users/lookup?${searchParams.toString()}`, {
    method: 'GET',
    cache: 'no-store',
  })
  if (!res.ok) {
    throw new Error(`Failed to lookup users (${res.status})`)
  }
  return res.json()
}
