import { fetchWithAuth } from '@/lib/api/auth'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'

const API_BASE_URL = getBackendBaseUrl()

export interface DateRange {
  startDate: string // YYYY-MM-DD
  endDate: string   // YYYY-MM-DD
}

export interface CountByDay {
  date: string
  count: number
}

export interface MessagesByDay {
  date: string
  total: number
  user: number
  assistant: number
}

export interface OverviewTodayStats {
  active_users: number
  conversations: number
  spend_usd: number
  time_saved_minutes: number
  time_lost_minutes: number
}

export interface OverviewLifetimeStats {
  helpful_rate: number
  total_ratings: number
}

export interface OverviewSummary {
  generated_at: string
  days: number
  include_admins: boolean
  reporting_timezone: string
  today: OverviewTodayStats
  lifetime: OverviewLifetimeStats
  conversations_per_day: CountByDay[]
  messages_per_day: MessagesByDay[]
}

export async function fetchOverview(
  dateRange: DateRange,
  includeAdmins = false
): Promise<OverviewSummary> {
  const params = new URLSearchParams({
    start_date: dateRange.startDate,
    end_date: dateRange.endDate,
    include_admins: String(includeAdmins),
  })
  const res = await fetchWithAuth(
    `${API_BASE_URL}/admin/overview?${params}`,
    { cache: 'no-store' }
  )
  if (!res.ok) {
    throw new Error(`Failed to fetch overview (${res.status})`)
  }
  return res.json()
}
