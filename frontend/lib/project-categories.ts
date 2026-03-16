export const PROJECT_CATEGORY_OPTIONS = [
  "Clients & Programmes",
  "Service Lines",
  "Sectors",
  "Regions & Markets",
  "Business Functions",
] as const;

export type ProjectCategory = typeof PROJECT_CATEGORY_OPTIONS[number];
