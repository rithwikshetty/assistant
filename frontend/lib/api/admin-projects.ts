import { fetchWithAuth } from '@/lib/api/auth'
import type { ApiSchema } from '@/lib/api/generated/types'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'
import { parseApiError } from '@/lib/api/errors'

const API_BASE_URL = getBackendBaseUrl()

export type CreatePublicProjectPayload = {
  name: string
  ownerEmail: string
  description?: string
  category?: string
}
export type AdminCreatePublicProjectResponse = ApiSchema<"AdminCreatePublicProjectResponse">
export type AdminPublicProjectListItem = ApiSchema<"AdminPublicProjectListItem">
export type AdminPublicProjectListResponse = ApiSchema<"AdminPublicProjectListResponse">
export type AdminDeleteProjectResponse = ApiSchema<"AdminDeleteProjectResponse">

export async function createPublicProject(payload: CreatePublicProjectPayload): Promise<AdminCreatePublicProjectResponse> {
  const res = await fetchWithAuth(`${API_BASE_URL}/admin/projects/public`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: payload.name,
      owner_email: payload.ownerEmail,
      description: payload.description ?? null,
      category: payload.category ?? null,
    }),
  })
  if (!res.ok) await parseApiError(res, 'Failed to create project')
  return res.json() as Promise<AdminCreatePublicProjectResponse>
}

export async function listAdminPublicProjects(): Promise<AdminPublicProjectListResponse> {
  const res = await fetchWithAuth(`${API_BASE_URL}/admin/projects/public-list`, { cache: 'no-store' })
  if (!res.ok) await parseApiError(res, 'Failed to load projects')
  return res.json()
}

export async function deletePublicProject(projectId: string): Promise<AdminDeleteProjectResponse> {
  const res = await fetchWithAuth(`${API_BASE_URL}/admin/projects/${projectId}`, { method: 'DELETE' })
  if (!res.ok) await parseApiError(res, 'Failed to delete project')
  return res.json() as Promise<AdminDeleteProjectResponse>
}
