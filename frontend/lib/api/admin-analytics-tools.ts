import { fetchWithAuth } from '@/lib/api/auth'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'

const API_BASE_URL = getBackendBaseUrl()

export interface DateRange {
  startDate: string // YYYY-MM-DD
  endDate: string   // YYYY-MM-DD
}

export interface ToolDistributionItem {
  tool_name: string
  call_count: number
  error_count: number
  percentage: number
}

export interface ToolDiversityMetrics {
  unique_tools_used_last_n_days: number
  conversations_with_any_tool_last_n_days: number
  conversations_with_multi_tool_last_n_days: number
  conversations_with_any_tool_rate_last_n_days: number
  conversations_with_multi_tool_rate_last_n_days: number
  avg_unique_tools_per_active_conversation_last_n_days: number
}

export interface ToolsDistributionSummary {
  generated_at: string
  days: number
  include_admins: boolean
  reporting_timezone: string
  total_calls: number
  total_errors: number
  tools: ToolDistributionItem[]
  diversity?: ToolDiversityMetrics
}

export async function fetchToolsDistribution(
  dateRange: DateRange,
  includeAdmins = false
): Promise<ToolsDistributionSummary> {
  const params = new URLSearchParams({
    start_date: dateRange.startDate,
    end_date: dateRange.endDate,
    include_admins: String(includeAdmins),
  })
  const res = await fetchWithAuth(
    `${API_BASE_URL}/admin/analytics/tools/distribution?${params}`,
    { cache: 'no-store' }
  )
  if (!res.ok) {
    throw new Error(`Failed to fetch tools distribution (${res.status})`)
  }
  return res.json()
}
