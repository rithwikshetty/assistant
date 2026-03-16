import { fetchWithAuth } from '@/lib/api/auth'
import { getBackendBaseUrl } from '@/lib/utils/backend-url'

const API_BASE_URL = getBackendBaseUrl()

export interface DateRange {
  startDate: string // YYYY-MM-DD
  endDate: string   // YYYY-MM-DD
}

export interface TimeTotals {
  time_saved_minutes: number
  time_spent_minutes: number
}

export interface DeliverableTimeSavingsItem {
  deliverable: string
  saved_minutes: number
  spent_minutes: number
  saved_recent: number
  spent_recent: number
}

export interface TimeSeriesPoint {
  date: string
  saved: number
  spent: number
}

export interface TimeSavingsInsights {
  generated_at: string
  days: number
  include_admins: boolean
  reporting_timezone: string
  totals: TimeTotals
  last_n_days: TimeTotals
  time_series: TimeSeriesPoint[]
  by_deliverable: DeliverableTimeSavingsItem[]
}

export async function fetchTimeSavingsInsights(
  dateRange: DateRange,
  includeAdmins = false
): Promise<TimeSavingsInsights> {
  const params = new URLSearchParams({
    start_date: dateRange.startDate,
    end_date: dateRange.endDate,
    include_admins: String(includeAdmins),
  })
  const res = await fetchWithAuth(
    `${API_BASE_URL}/admin/analytics/time-savings?${params}`,
    { cache: 'no-store' }
  )
  if (!res.ok) {
    throw new Error(`Failed to fetch time savings (${res.status})`)
  }
  return res.json()
}
