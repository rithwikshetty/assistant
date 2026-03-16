/**
 * Shared types for message-list components
 */

import type { Message, MessageContentPart } from "@/hooks/use-chat";

// ============================================================================
// Message List Props
// ============================================================================

export type MessageListProps = {
  messages: Message[];
  /** Conversation ID for actions */
  conversationId?: string;
  /** Whether the viewer owns this conversation */
  viewerIsOwner?: boolean;
  /** Whether the viewer can give feedback */
  canGiveFeedback?: boolean;
  /** Scrollable transcript container for virtualization */
  getScrollElement?: () => HTMLDivElement | null;
  /** Custom class name */
  className?: string;
};

// ============================================================================
// Content Segments
// ============================================================================

export type ContentSegment =
  | { type: "text"; text: string }
  | { type: "divider"; label: string }
  | { type: "visible-tool"; part: MessageContentPart }
  | { type: "tool-group"; groupKey: string; parts: MessageContentPart[] }
  | { type: "part"; part: MessageContentPart };

// ============================================================================
// Tool Result Types
// ============================================================================

export type WebSearchCitation = {
  index?: number;
  url: string;
  title?: string;
  snippet?: string;
};

export type KnowledgeSource = {
  content?: string;
  score?: number | null;
  metadata?: Record<string, unknown> | null;
};

export type KnowledgeResult = {
  content?: string;
  message?: string;
  sources?: KnowledgeSource[];
  files?: string[];
  results?: Array<{
    file_id?: string;
    filename?: string;
    excerpts?: string[];
    file_type?: string;
    file_size?: number;
    match_count?: number;
    filename_match?: boolean;
  }>;
  total_nodes?: number;
  error?: string;
};

export type CalculationResult = {
  operation?: string;
  operation_label?: string;
  precision?: number | null;
  inputs?: Record<string, { label?: string | null; value?: number | null; display?: string | null }>;
  result?: { label?: string | null; value?: number | null; display?: string | null };
  explanation?: string | null;
  reasoning?: string | null;
  details?: Array<{ label?: string | null; value?: string | null }> | null;
  error?: string;
};

// BCIS Index types
export type BcisIndexArgs = {
  index_type: "location" | "inflation" | "labour";
  location?: string;
  date?: string;
};

export type LocationIndexItem = { location: string; index_value: number | null };

export type InflationIndexItem = {
  date: string;
  material_cost_index?: number | null;
  labour_cost_index?: number | null;
  plant_cost_index?: number | null;
  building_cost_index?: number | null;
  tender_price_index?: number | null;
};

export type LabourIndexItem = { date: string; index_value: number | null };

export type BcisIndexResult = {
  index_type: "location" | "inflation" | "labour";
  results: Array<LocationIndexItem | InflationIndexItem | LabourIndexItem>;
  count: number;
  error?: string;
  filters_applied?: Partial<BcisIndexArgs>;
};

// Rates types
export type RateItem = {
  description: string;
  category?: string | null;
  key_rate?: string | null;
  nrm_element?: string | null;
  type?: string | null;
  sub_component?: string | null;
  rate?: number | null;
  uom?: string | null;
  total?: number | null;
  quantity?: number | null;
  source_file?: string | null;
  base_date?: string | null;
  material_index?: number | null;
  updated?: string | null;
  sector?: string | null;
  location?: string | null;
  base_quarter?: string | null;
  project_code?: string | null;
};

export type RatesSearchResult = {
  rates?: RateItem[];
  count?: number;
  filters_applied?: Record<string, unknown>;
  error?: string;
};

// Cost Adjustment types
export type CostAdjustmentArgs = {
  base_value: number;
  base_index: number;
  target_index: number;
  adjustment_type?: "index" | "percentage";
  percentage?: number;
  precision?: number;
  reasoning?: string;
};

export type CostAdjustmentResult = {
  adjusted_value: number;
  adjustment_amount: number;
  change_percent: number;
  summary?: string;
  reasoning?: string;
};

// Re-export Message types for convenience
export type { Message, MessageContentPart } from "@/hooks/use-chat";
