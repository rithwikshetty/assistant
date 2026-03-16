import { fetchWithAuth } from '@/lib/api/auth'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'

const API_BASE_URL = getBackendBaseUrl()

export interface CountItem { date: string; count: number }
export interface MessagesByDay { date: string; total: number; user: number; assistant: number }
export interface TopUserItem { user_id: string; email: string; count: number; size_bytes?: number | null }
export interface FileTypeBreakdown { file_type: string; count: number; size_bytes: number }

export interface MessageUsageSnapshot {
  message_count: number
  effective_input_tokens: number
  output_tokens: number
  total_tokens: number
  avg_response_latency_ms?: number | null
  avg_tool_calls?: number | null
  cost_usd?: number
}

export interface ModelUsageSnapshot {
  model: string
  source?: 'chat' | 'non_chat' | 'mixed'
  processes?: string[]
  message_count: number
  effective_input_tokens: number
  output_tokens: number
  total_tokens: number
  avg_response_latency_ms?: number | null
  cost_usd: number
}

export interface ModelCostByDay {
  date: string
  total: number
  models: Record<string, number>
}

export interface UsageSummary {
  generated_at: string
  range_start: string
  range_end: string
  days: number
  reporting_timezone: string
  total_users: number
  total_conversations: number
  total_messages: number
  total_files: number
  total_storage_bytes: number
  messages_last_n_days: number
  file_uploads_last_n_days: number
  users_per_day: CountItem[]
  conversations_per_day: CountItem[]
  messages_per_day: MessagesByDay[]
  file_uploads_per_day: CountItem[]
  active_users_per_day: CountItem[]
  files_by_type: FileTypeBreakdown[]
  users_by_department: TopUserItem[]
  top_users_by_messages: TopUserItem[]
  top_uploaders: TopUserItem[]
  approx_avg_response_secs: number
  assistant_usage_last_n_days: MessageUsageSnapshot
  assistant_usage_lifetime: MessageUsageSnapshot
  model_usage_last_n_days: ModelUsageSnapshot[]
  model_usage_chat_last_n_days: ModelUsageSnapshot[]
  model_usage_non_chat_last_n_days: ModelUsageSnapshot[]
  assistant_cost_last_n_days: number
  non_chat_cost_last_n_days: number
  total_model_cost_last_n_days: number
  model_cost_timeseries: ModelCostByDay[]
  model_cost_timeseries_chat: ModelCostByDay[]
  model_cost_timeseries_non_chat: ModelCostByDay[]
}

export interface DateRange {
  startDate: string // YYYY-MM-DD
  endDate: string   // YYYY-MM-DD
}

export async function fetchUsage(
  dateRange: DateRange,
  includeAdmins = false
): Promise<UsageSummary> {
  const params = new URLSearchParams({
    start_date: dateRange.startDate,
    end_date: dateRange.endDate,
    include_admins: String(includeAdmins),
  })
  const res = await fetchWithAuth(
    `${API_BASE_URL}/admin/usage?${params}`,
    { cache: 'no-store' }
  )
  if (!res.ok) throw new Error(`Failed to fetch usage (${res.status})`)
  return res.json()
}
