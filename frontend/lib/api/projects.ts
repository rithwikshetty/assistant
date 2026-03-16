import { fetchWithAuth } from '@/lib/api/auth'
import type { ApiSchema } from '@/lib/api/generated/types'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'
import { parseApiError } from '@/lib/api/errors'

const API_BASE_URL = getBackendBaseUrl()

export type ProjectOwnerSummary = ApiSchema<"BrowseProjectOwner">
export type PublicProjectItem = ApiSchema<"BrowseProjectItem">
export type BrowseProjectsResponse = ApiSchema<"BrowseProjectsResponse">
export type ProjectJoinLeaveResponse = ApiSchema<"ProjectJoinLeaveResponse">
export type ProjectVisibilityUpdateResponse = ApiSchema<"ProjectVisibilityUpdateResponse">

export async function browsePublicProjects(category?: string): Promise<BrowseProjectsResponse> {
  const url = new URL(`${API_BASE_URL}/projects/browse`)
  if (category) url.searchParams.set('category', category)
  const res = await fetchWithAuth(url.toString(), { cache: 'no-store' })
  if (!res.ok) await parseApiError(res, 'Failed to browse projects')
  return res.json()
}

export async function joinPublicProject(projectId: string): Promise<ProjectJoinLeaveResponse> {
  const res = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/join`, {
    method: 'POST',
    cache: 'no-store',
  })
  if (!res.ok) await parseApiError(res, 'Failed to join project')
  return res.json()
}

export async function leavePublicProject(projectId: string): Promise<ProjectJoinLeaveResponse> {
  const res = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/leave`, {
    method: 'POST',
    cache: 'no-store',
  })
  if (!res.ok) await parseApiError(res, 'Failed to leave project')
  return res.json()
}

export async function updateProjectVisibility(projectId: string, isPublic: boolean) {
  const res = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/visibility`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_public: isPublic })
  })
  if (!res.ok) await parseApiError(res, 'Failed to update visibility')
  return res.json() as Promise<ProjectVisibilityUpdateResponse>
}

// Note: Owner promotion is handled via project member role updates
// (see `updateProjectMemberRole` in project-sharing API), to keep API surface minimal.
