import { fetchWithAuth } from "@/lib/api/auth";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";

const API_BASE_URL = getBackendBaseUrl();

export interface DateRange {
  startDate: string; // YYYY-MM-DD
  endDate: string; // YYYY-MM-DD
}

export interface SectorDistributionItem {
  [key: string]: string | number;
  sector: string;
  conversation_count: number;
  percentage: number;
}

export interface SectorDistributionSummary {
  generated_at: string;
  reporting_timezone: string;
  start_date: string;
  end_date: string;
  include_admins: boolean;
  total_conversations: number;
  sectors: SectorDistributionItem[];
}

export async function fetchSectorDistribution(
  dateRange: DateRange,
  includeAdmins = false,
): Promise<SectorDistributionSummary> {
  const params = new URLSearchParams({
    start_date: dateRange.startDate,
    end_date: dateRange.endDate,
    include_admins: String(includeAdmins),
  });

  const response = await fetchWithAuth(
    `${API_BASE_URL}/admin/analytics/sectors?${params}`,
    { cache: "no-store" },
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch sector distribution (${response.status})`);
  }

  return response.json();
}
