import { useCallback, useState } from "react";
import type { MouseEvent } from "react";

type CopyTarget = MouseEvent<HTMLButtonElement>;

const COPY_RESET_TIMEOUT = 2000;

/**
 * Convert SVG elements to PNG data URLs for copying
 */
async function svgToPng(svgElement: SVGElement): Promise<string> {
  return new Promise((resolve, reject) => {
    try {
      const bbox = svgElement.getBoundingClientRect();
      const viewBox = svgElement.getAttribute("viewBox");
      const [viewBoxWidth, viewBoxHeight] = viewBox
        ? viewBox
            .split(/\s+/)
            .slice(-2)
            .map((value) => Number.parseFloat(value) || 0)
        : [0, 0];
      const widthAttr = Number.parseFloat(svgElement.getAttribute("width") ?? "") || 0;
      const heightAttr = Number.parseFloat(svgElement.getAttribute("height") ?? "") || 0;
      const width = Math.max(bbox.width, widthAttr, viewBoxWidth);
      const height = Math.max(bbox.height, heightAttr, viewBoxHeight);

      if (!width || !height) {
        reject(new Error("SVG has invalid dimensions"));
        return;
      }

      const svgClone = svgElement.cloneNode(true) as SVGElement;
      svgClone.setAttribute('width', String(width));
      svgClone.setAttribute('height', String(height));

      const svgString = new XMLSerializer().serializeToString(svgClone);
      const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);

      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = width * 2;
        canvas.height = height * 2;

        const ctx = canvas.getContext('2d');
        if (!ctx) {
          reject(new Error('Could not get canvas context'));
          URL.revokeObjectURL(url);
          return;
        }

        ctx.scale(2, 2);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);

        const pngDataUrl = canvas.toDataURL('image/png');
        URL.revokeObjectURL(url);
        resolve(pngDataUrl);
      };

      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error('Failed to load SVG image'));
      };

      img.src = url;
    } catch (error) {
      reject(error);
    }
  });
}

/**
 * Clone the provided content root and replace any Recharts SVGs with PNG images.
 */
async function serializeContentWithCharts(contentRoot: HTMLElement): Promise<string> {
  const clonedContent = contentRoot.cloneNode(true) as HTMLElement;

  // Find chart tools in the ORIGINAL content first (so we have proper dimensions)
  const originalToolElements = Array.from(
    contentRoot.querySelectorAll(".tool-connectable, .tool-connectable-group")
  );

  // Find all SVGs in original content and filter to only large chart SVGs (not legend icons)
  const allSvgs = Array.from(
    contentRoot.querySelectorAll<SVGElement>("svg.recharts-surface"),
  );

  const originalCharts = allSvgs.filter((svg) => {
    const bbox = svg.getBoundingClientRect();
    // Only include SVGs larger than 50x50 (excludes legend icons which are ~14x14)
    return bbox.width > 50 && bbox.height > 50;
  });

  if (originalCharts.length === 0) {
    // No charts to convert, just remove all tool content for a clean copy
    clonedContent.querySelectorAll(".tool-connectable, .tool-connectable-group").forEach((node) => node.remove());
    return clonedContent.innerHTML;
  }

  // Map original tools to their chart status
  const toolHasChart = originalToolElements.map((element) => {
    // Check for recharts SVG
    const svgs = Array.from(element.querySelectorAll<SVGElement>("svg.recharts-surface"));
    return svgs.some((svg) => {
      const bbox = svg.getBoundingClientRect();
      return bbox.width > 50 && bbox.height > 50;
    });
  });

  // Process cloned tool elements, using the chart status from original
  const clonedToolElements = Array.from(
    clonedContent.querySelectorAll(".tool-connectable, .tool-connectable-group")
  );

  for (let i = 0; i < clonedToolElements.length; i++) {
    const node = clonedToolElements[i];
    const hasChart = toolHasChart[i];

    if (!hasChart) {
      // Remove non-chart tools
      node.remove();
    } else {
      const originalTool = originalToolElements[i];

      // For chart tools: find all charts in this tool and convert each to PNG
      const chartsInTool = Array.from(originalTool.querySelectorAll<SVGElement>("svg.recharts-surface")).filter((svg) => {
        const bbox = svg.getBoundingClientRect();
        return bbox.width > 50 && bbox.height > 50;
      });

      if (chartsInTool.length === 0) {
        node.remove();
        continue;
      }

      // Create a container for all charts in this tool
      const container = document.createElement("div");

      for (const originalSvg of chartsInTool) {
        try {
          const pngDataUrl = await svgToPng(originalSvg);

          // Find the chart title (h3 inside the chart container)
          const chartContainer = originalSvg.closest(".space-y-4");
          const titleElement = chartContainer?.querySelector("h3");
          const titleText = titleElement?.textContent?.trim();

          // Create a wrapper for this chart with title
          const chartWrapper = document.createElement("div");
          chartWrapper.style.marginBottom = "2em";

          // Add title if it exists
          if (titleText) {
            const title = document.createElement("h3");
            title.textContent = titleText;
            title.style.fontSize = "16px";
            title.style.fontWeight = "600";
            title.style.marginBottom = "0.5em";
            chartWrapper.appendChild(title);
          }

          // Create img element for this chart
          const img = document.createElement("img");
          img.src = pngDataUrl;
          img.style.maxWidth = "100%";
          img.style.height = "auto";
          img.style.display = "block";
          img.alt = titleText ? `${titleText} chart` : "Chart";

          chartWrapper.appendChild(img);
          container.appendChild(chartWrapper);
        } catch (error) {
          console.warn("Chart PNG conversion skipped:", error);
        }
      }

      // Replace the ENTIRE tool container with the container of images
      if (container.children.length > 0) {
        node.replaceWith(container);
      } else {
        node.remove();
      }
    }
  }

  return clonedContent.innerHTML;
}

export const useCopyMessageContent = () => {
  const [copied, setCopied] = useState(false);

  const resetLater = useCallback(() => {
    setTimeout(() => setCopied(false), COPY_RESET_TIMEOUT);
  }, []);

  const copyFromRoot = useCallback(async (root: HTMLElement) => {
    const contentRoot = root.querySelector<HTMLElement>('[data-message-content]') ?? root;

    // Get plain text without tool content (but keep charts)
    const contentClone = contentRoot.cloneNode(true) as HTMLElement;
    contentClone
      .querySelectorAll(".tool-connectable, .tool-connectable-group")
      .forEach((node) => {
        const element = node as HTMLElement;
        // Check if this tool has a LARGE chart SVG (not just legend icons)
        const svgs = Array.from(element.querySelectorAll<SVGElement>("svg.recharts-surface"));
        const hasChart = svgs.some((svg) => {
          const bbox = svg.getBoundingClientRect();
          return bbox.width > 50 && bbox.height > 50;
        });
        // Keep chart tools, remove everything else
        if (!hasChart) {
          node.remove();
        }
      });
    const plainText = contentClone.innerText;

    if (!plainText || !plainText.trim()) return;

    let html = contentRoot.innerHTML;

    try {
      html = await serializeContentWithCharts(contentRoot);

      // Wrap in proper HTML document for Word compatibility
      html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.6; }
img { max-width: 100%; height: auto; display: block; margin: 1em 0; }
</style>
</head>
<body>
${html}
</body>
</html>`;
    } catch (error) {
      console.error("Failed to process charts:", error);
      html = contentRoot.innerHTML;
    }

    try {
      if (
        html &&
        "clipboard" in navigator &&
        "write" in navigator.clipboard &&
        typeof ClipboardItem !== "undefined"
      ) {
        const item = new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([plainText], { type: "text/plain" }),
        });
        await navigator.clipboard.write([item]);
      } else {
        await navigator.clipboard.writeText(plainText);
      }
    } catch (error) {
      console.error("Clipboard write failed:", error);
      await navigator.clipboard.writeText(plainText);
    }
  }, []);

  const handleCopy = useCallback(
    async (event: CopyTarget) => {
      const button = event.currentTarget as HTMLElement;
      const root = button.closest(".group") as HTMLElement | null;
      if (!root) return;

      try {
        await copyFromRoot(root);
        setCopied(true);
        resetLater();
      } catch (error) {
        console.error("Copy failed with error:", error);
      }
    },
    [copyFromRoot, resetLater],
  );

  return { copied, handleCopy };
};
