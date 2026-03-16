import { fetchWithAuth } from '@/lib/api/auth';
import { getBackendBaseUrl } from '@/lib/utils/backend-url';
import { parseApiError } from '@/lib/api/errors';
import type { ApiSchema } from '@/lib/api/generated/types';

const API_BASE_URL = getBackendBaseUrl();

export type ProjectMember = ApiSchema<"ProjectMemberResponse">;
export type ProjectMemberRole = ProjectMember["role"];
export type ProjectMembersResponse = ApiSchema<"ProjectMembersListResponse">;
export type ProjectShareResponse = ApiSchema<"ProjectShareResponse">;
export type ProjectJoinResponse = ApiSchema<"ProjectJoinResponse">;
export type ProjectJoinLeaveResponse = ApiSchema<"ProjectJoinLeaveResponse">;


export async function generateProjectShareLink(projectId: string): Promise<ProjectShareResponse> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/share`, {
    method: 'POST',
  });

  if (!response.ok) await parseApiError(response, 'Failed to generate project share link');

  return response.json();
}

export async function getProjectMembers(projectId: string): Promise<ProjectMembersResponse> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/members`);

  if (!response.ok) await parseApiError(response, 'Failed to fetch project members');

  return response.json();
}

export async function joinProjectViaShareLink(shareToken: string): Promise<ProjectJoinResponse> {
  const response = await fetchWithAuth(`${API_BASE_URL}/share/projects/${shareToken}/join`, {
    method: 'POST',
  });

  if (!response.ok) await parseApiError(response, 'Failed to join project');

  return response.json();
}

export async function leaveProject(projectId: string): Promise<ProjectJoinLeaveResponse> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/leave`, {
    method: 'POST',
  });

  if (!response.ok) await parseApiError(response, 'Failed to leave project');

  return response.json();
}

export async function updateProjectMemberRole(
  projectId: string,
  memberId: string,
  role: ProjectMemberRole,
): Promise<ProjectMember> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/members/${memberId}/role`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  });

  if (!response.ok) await parseApiError(response, 'Failed to update member role');

  return response.json() as Promise<ProjectMember>;
}
