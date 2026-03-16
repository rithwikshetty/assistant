import { cloneElement, useLayoutEffect, useRef, useState, type CSSProperties, type ReactElement } from "react";
import { cn } from "@/lib/utils";

type ChartElementProps = {
  width?: number;
  height?: number;
};

type SafeResponsiveContainerProps = {
  children: ReactElement<ChartElementProps>;
  className?: string;
  style?: CSSProperties;
};

export function SafeResponsiveContainer({ children, className, style }: SafeResponsiveContainerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number } | null>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const updateDimensions = () => {
      const { width, height } = container.getBoundingClientRect();
      if (width > 0 && height > 0) {
        setDimensions((previous) => {
          const roundedWidth = Math.round(width);
          const roundedHeight = Math.round(height);
          if (
            previous &&
            previous.width === roundedWidth &&
            previous.height === roundedHeight
          ) {
            return previous;
          }
          return {
            width: roundedWidth,
            height: roundedHeight,
          };
        });
      } else {
        setDimensions(null);
      }
    };

    updateDimensions();

    const resizeObserver = new ResizeObserver(updateDimensions);
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
    };
  }, []);

  return (
    <div ref={containerRef} className={cn("h-full w-full min-w-0", className)} style={style}>
      {dimensions
        ? cloneElement(children, {
            width: dimensions.width,
            height: dimensions.height,
          })
        : null}
    </div>
  );
}
