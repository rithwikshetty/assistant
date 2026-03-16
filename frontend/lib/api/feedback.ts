// Simple Feedback API client
import { fetchWithAuth } from './auth'
import type { ApiSchema } from '@/lib/api/generated/types'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'

const API_BASE_URL = getBackendBaseUrl()

export type BugReportCreate = ApiSchema<"BugReportCreate">
export type BugReportResponse = ApiSchema<"BugReportResponse">
export type BugSeverity = BugReportCreate["severity"]
export type MessageFeedbackCreate = ApiSchema<"MessageFeedbackCreate">
export type MessageFeedbackResponse = ApiSchema<"MessageFeedbackResponse">
export type MessageFeedbackDeleteResponse = ApiSchema<"MessageFeedbackDeleteResponse">
export type MessageFeedbackRating = MessageFeedbackCreate["rating"]

export async function submitBugReport(payload: BugReportCreate): Promise<BugReportResponse> {
  const resp = await fetchWithAuth(`${API_BASE_URL}/feedback/bug`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  if (resp.status === 401) {
    throw new Error('Request failed. Please retry.')
  }

  if (!resp.ok) {
    const detail = await safeDetail(resp)
    throw new Error(detail || `Failed to submit bug (${resp.status})`)
  }

  return resp.json()
}

export async function submitMessageFeedback(payload: MessageFeedbackCreate): Promise<MessageFeedbackResponse> {
  const resp = await fetchWithAuth(`${API_BASE_URL}/feedback/message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  if (resp.status === 401) {
    throw new Error('Request failed. Please retry.')
  }

  if (!resp.ok) {
    const detail = await safeDetail(resp)
    throw new Error(detail || `Failed to submit feedback (${resp.status})`)
  }

  return resp.json()
}

export async function deleteMessageFeedback(messageId: string): Promise<MessageFeedbackDeleteResponse> {
  const resp = await fetchWithAuth(`${API_BASE_URL}/feedback/message/${messageId}`, {
    method: 'DELETE',
  })

  if (resp.status === 401) {
    throw new Error('Request failed. Please retry.')
  }

  if (!resp.ok && resp.status !== 204) {
    const detail = await safeDetail(resp)
    throw new Error(detail || `Failed to delete feedback (${resp.status})`)
  }

  if (resp.status === 204) {
    return { conversation_requires_feedback: true }
  }

  try {
    const data = (await resp.json()) as MessageFeedbackDeleteResponse
    if (typeof data?.conversation_requires_feedback === 'boolean') {
      return data
    }
  } catch {
    // fall through to default
  }

  return { conversation_requires_feedback: true }
}

async function safeDetail(resp: Response): Promise<string | null> {
  try {
    const data = await resp.json()
    return data?.detail || null
  } catch {
    return null
  }
}
