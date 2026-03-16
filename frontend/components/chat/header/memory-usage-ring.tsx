import { cn } from "@/lib/utils";

export const MemoryUsageRing = ({
  percent,
  className,
}: {
  percent: number;
  className?: string;
}) => {
  const clamped = Math.min(100, Math.max(0, Math.round(percent)));
  const radius = 6;
  const circumference = 2 * Math.PI * radius;
  const strokeOffset = circumference * (1 - clamped / 100);

  return (
    <svg
      viewBox="0 0 16 16"
      className={cn("shrink-0", className)}
      aria-hidden="true"
    >
      <circle
        cx="8"
        cy="8"
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth="2"
      />
      <circle
        cx="8"
        cy="8"
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={`${circumference} ${circumference}`}
        strokeDashoffset={strokeOffset}
        transform="rotate(-90 8 8)"
      />
    </svg>
  );
};
