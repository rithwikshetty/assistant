import { fetchWithAuth } from "@/lib/api/auth";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";

const API_BASE_URL = getBackendBaseUrl();

export interface DateRange {
  startDate: string; // YYYY-MM-DD
  endDate: string; // YYYY-MM-DD
}

export interface BugSummary {
  total: number;
  total_last_n_days: number;
  by_severity: Record<string, number>;
  last_n_days_by_severity: Record<string, number>;
}

export async function fetchBugSummary(
  dateRange: DateRange,
  includeAdmins = false,
): Promise<BugSummary> {
  const params = new URLSearchParams({
    start_date: dateRange.startDate,
    end_date: dateRange.endDate,
    include_admins: String(includeAdmins),
  });

  const response = await fetchWithAuth(
    `${API_BASE_URL}/admin/analytics/bugs?${params}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch bug summary (${response.status})`);
  }
  return response.json();
}
