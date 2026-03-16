
import { useMemo, type FC } from "react";
import type { Icon as IconComponent } from "@phosphor-icons/react";
import {
  BookOpen as BookOpenIcon,
  FileText as FileTextIcon,
  Globe,
  Buildings,
  Database,
  Stack as Layers3Icon,
  X as XIcon,
  ChartBar,
  ArrowSquareOut,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { InsightSidebarPayload } from "@/components/chat/insights/insight-sidebar-context";
import { cn } from "@/lib/utils";
import {
  collectMessageInsights,
  type InsightCategory,
  type InsightGroup as CoreInsightGroup,
} from "@/lib/insights/collect";

export type MessageInsightsSidebarProps = {
  open: boolean;
  onClose: () => void;
  payload: InsightSidebarPayload | null;
  className?: string;
  headingId?: string;
};

const INSIGHT_CATEGORY_CONFIG: Record<InsightCategory, { label: string; icon: IconComponent }> = {
  web: { label: "Web search", icon: Globe },
  knowledge: { label: "Knowledge", icon: BookOpenIcon },
  project: { label: "Project files", icon: FileTextIcon },
  other: { label: "Other references", icon: Layers3Icon },
};

type UiInsightGroup = {
  category: InsightCategory;
  label: string;
  icon: IconComponent;
  entries: CoreInsightGroup["entries"];
};

export const MessageInsightsSidebar: FC<MessageInsightsSidebarProps> = ({
  open,
  onClose,
  payload,
  className,
  headingId,
}) => {
  const message = payload?.message;
  const explicitCount = payload?.sourceCount;

  const { groups: rawGroups, total, hasRates, ratesCount, rates, bcisIndices, projectDetails } = useMemo(
    () => collectMessageInsights(message),
    [message],
  );
  const sourceCount =
    typeof explicitCount === "number"
      ? explicitCount
      : total + (ratesCount ?? 0) + bcisIndices.length + projectDetails.length;

  // Map to UI groups (labels/icons)
  const visibleGroups: UiInsightGroup[] = useMemo(
    () =>
      rawGroups.map((g) => ({
        category: g.category,
        entries: g.entries,
        label: INSIGHT_CATEGORY_CONFIG[g.category].label,
        icon: INSIGHT_CATEGORY_CONFIG[g.category].icon,
      })),
    [rawGroups],
  );

  if (!open) {
    return null;
  }

  return (
    <aside
      role="complementary"
      aria-labelledby={headingId}
      className={cn(
        "flex h-full max-h-full w-full min-h-0 min-w-0 flex-col overflow-hidden bg-background type-size-14 shadow-sm",
        className,
      )}
    >
      <div className="flex h-16 items-center justify-between gap-3 border-b border-border/20 px-4">
        <div className="flex items-baseline gap-1">
          <span id={headingId} className="type-size-12 font-semibold uppercase tracking-wide text-muted-foreground">
            Sources
          </span>
          {typeof sourceCount === "number" ? (
            <>
              <span className="text-muted-foreground/50" aria-hidden>
                ·
              </span>
              <span className="type-size-14 font-normal text-muted-foreground/80">{sourceCount}</span>
            </>
          ) : null}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="rounded-sm size-6 p-1 text-muted-foreground hover:bg-muted/70 hover:text-foreground"
          aria-label="Close sources"
        >
          <XIcon className="h-4 w-4" aria-hidden />
        </Button>
      </div>

      <div
        className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 py-4"
        style={{ scrollbarGutter: "stable both-edges" }}
      >
        {visibleGroups.length === 0 && !hasRates && bcisIndices.length === 0 && projectDetails.length === 0 ? (
          <p className="type-size-14 text-muted-foreground">
            No sources have been linked yet. The assistant may still be working or relied on internal knowledge for this
            response.
          </p>
        ) : (
          <>
            {hasRates && rates.length > 0 ? (
              <section className="border-t border-border/50 pt-6 pb-6 first:border-t-0 first:pt-0">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 type-size-12 font-semibold uppercase tracking-wide text-muted-foreground">
                    <Database className="h-3.5 w-3.5" aria-hidden />
                    <span>Rates</span>
                  </div>
                  <span className="type-size-12 text-muted-foreground/70">{rates.length}</span>
                </div>
                <ul className="space-y-3">
                  {rates.map((rate) => (
                    <li key={rate.id} className="space-y-1">
                      <div className="flex items-start justify-between gap-2">
                        <p className="type-size-14 font-medium text-foreground line-clamp-2" title={rate.description}>
                          {rate.description}
                        </p>
                        {typeof rate.rate === "number" ? (
                          <div className="text-right shrink-0">
                            <div className="type-size-14 font-semibold whitespace-nowrap">
                              {rate.rate.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                            </div>
                          </div>
                        ) : null}
                      </div>
                      <div className="space-y-1 type-size-12 text-muted-foreground/80">
                        {rate.uom || rate.location || rate.sector || rate.base_date ? (
                          <p className="leading-snug">
                            {[rate.uom, rate.location, rate.sector, rate.base_date].filter(Boolean).join(" • ")}
                          </p>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {bcisIndices.length > 0 ? (
              <section className="border-t border-border/50 pt-6 pb-6 first:border-t-0 first:pt-0">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 type-size-12 font-semibold uppercase tracking-wide text-muted-foreground">
                    <ChartBar className="h-3.5 w-3.5" aria-hidden />
                    <span>BCIS Indices</span>
                  </div>
                  <span className="type-size-12 text-muted-foreground/70">{bcisIndices.length}</span>
                </div>
                <ul className="space-y-3">
                  {bcisIndices.map((index) => (
                    <li key={index.id} className="space-y-1">
                      {index.indexType === "inflation" ? (
                        <>
                          <p className="type-size-14 font-medium text-foreground">{index.label}</p>
                          <div className="space-y-1 type-size-12 text-muted-foreground/80">
                            <p className="leading-snug">
                              {[
                                index.material_cost_index != null && `Material: ${index.material_cost_index.toFixed(2)}`,
                                index.labour_cost_index != null && `Labour: ${index.labour_cost_index.toFixed(2)}`,
                                index.plant_cost_index != null && `Plant: ${index.plant_cost_index.toFixed(2)}`,
                                index.building_cost_index != null && `Building: ${index.building_cost_index.toFixed(2)}`,
                                index.tender_price_index != null && `Tender: ${index.tender_price_index.toFixed(2)}`,
                              ]
                                .filter(Boolean)
                                .join(" • ")}
                            </p>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="flex items-start justify-between gap-2">
                            <p className="type-size-14 font-medium text-foreground line-clamp-2" title={index.label}>
                              {index.label}
                            </p>
                            {index.value != null ? (
                              <div className="type-size-14 font-semibold whitespace-nowrap">{index.value.toFixed(2)}</div>
                            ) : null}
                          </div>
                          <div className="space-y-1 type-size-12 text-muted-foreground/80">
                            <p className="leading-snug capitalize">{index.indexType}</p>
                          </div>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {projectDetails.length > 0 ? (
              <section className="border-t border-border/50 pt-6 pb-6 first:border-t-0 first:pt-0">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 type-size-12 font-semibold uppercase tracking-wide text-muted-foreground">
                    <Buildings className="h-3.5 w-3.5" aria-hidden />
                    <span>Project Details</span>
                  </div>
                  <span className="type-size-12 text-muted-foreground/70">{projectDetails.length}</span>
                </div>
                <ul className="space-y-3">
                  {projectDetails.map((project) => (
                    <li key={project.id} className="space-y-1">
                      <p className="type-size-14 font-medium text-foreground line-clamp-2" title={project.name}>
                        {project.name}
                      </p>
                      <div className="space-y-1 type-size-12 text-muted-foreground/80">
                        {project.location || project.sector || project.primary_use || project.base_quarter || project.base_date || project.gia ? (
                          <p className="leading-snug">
                            {[
                              project.location,
                              project.sector,
                              project.primary_use,
                              project.base_quarter || project.base_date,
                              project.gia && `GIA ${project.gia.toLocaleString()}`,
                            ]
                              .filter(Boolean)
                              .join(" • ")}
                          </p>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {visibleGroups.map((group) => {
              const Icon = group.icon;
              return (
                <section key={group.category} className="border-t border-border/50 pt-6 pb-6 first:border-t-0 first:pt-0 last:pb-0">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 type-size-12 font-semibold uppercase tracking-wide text-muted-foreground">
                      <Icon className="h-3.5 w-3.5" aria-hidden />
                      <span>{group.label}</span>
                    </div>
                    <span className="type-size-12 text-muted-foreground/70">{group.entries.length}</span>
                  </div>

                  <ul className="space-y-3">
                    {group.entries.map((entry) => (
                      <li key={entry.id} className="space-y-1">
                        {entry.href ? (
                          <a
                            href={entry.href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="group/link flex items-start gap-1.5 text-left type-size-14 font-medium text-foreground underline-offset-4 hover:underline"
                          >
                            <span className="line-clamp-2 flex-1 min-w-0">{entry.primary}</span>
                            <ArrowSquareOut className="h-3 w-3 mt-0.5 flex-shrink-0 text-muted-foreground/40 group-hover/link:text-muted-foreground transition-colors" />
                          </a>
                        ) : (
                          <p className="line-clamp-2 type-size-14 font-medium text-foreground">{entry.primary}</p>
                        )}

                        <div className="space-y-1 type-size-12 text-muted-foreground/80">
                          {entry.secondary ? <p className="leading-snug">{entry.secondary}</p> : null}
                          {entry.description ? <p className="leading-snug">{entry.description}</p> : null}
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </>
        )}
      </div>
    </aside>
  );
};

MessageInsightsSidebar.displayName = "MessageInsightsSidebar";
