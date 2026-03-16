import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

const ROOT = path.resolve(process.cwd());
const SOURCE_DIRS = ["app", "components", "contexts", "hooks", "lib", "src", "types"];
const EXCLUDED_DIRS = new Set(["node_modules", "dist", "docs"]);
const ALLOWED_FONT_LITERAL_FILES = new Set([
  path.join(ROOT, "lib", "typography.ts"),
]);

const RAW_TEXT_SIZE_CLASS = /(?:^|[\s"'`])(?:[A-Za-z0-9_\-\[\]&/]+:)*text-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl|8xl|9xl|\[(?:\d+(?:\.\d+)?(?:px|rem))\])(?=$|[\s"'`])/g;
const INLINE_FONT_SIZE_LITERAL = /\bfontSize\s*:\s*(?:\d+(?:\.\d+)?|["']\d+(?:\.\d+)?(?:px|rem)["'])/g;

async function walk(dir) {
  const out = [];
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (EXCLUDED_DIRS.has(entry.name)) continue;
      out.push(...(await walk(fullPath)));
      continue;
    }
    if (!entry.isFile()) continue;
    if (!fullPath.endsWith(".ts") && !fullPath.endsWith(".tsx")) continue;
    out.push(fullPath);
  }
  return out;
}

function getLineAndColumn(content, index) {
  const upToIndex = content.slice(0, index);
  const line = upToIndex.split("\n").length;
  const lastLineStart = upToIndex.lastIndexOf("\n");
  const col = index - (lastLineStart + 1) + 1;
  return { line, col };
}

async function collectFiles() {
  const files = [];
  for (const dir of SOURCE_DIRS) {
    const fullDir = path.join(ROOT, dir);
    try {
      const dirStat = await stat(fullDir);
      if (!dirStat.isDirectory()) continue;
    } catch {
      continue;
    }
    files.push(...(await walk(fullDir)));
  }
  return files.sort();
}

function collectMatches(content, regex) {
  const matches = [];
  let match;
  while ((match = regex.exec(content)) !== null) {
    matches.push({ index: match.index, text: match[0].trim() });
  }
  return matches;
}

async function main() {
  const files = await collectFiles();
  const violations = [];

  for (const file of files) {
    const content = await readFile(file, "utf8");

    const rawClassMatches = collectMatches(content, new RegExp(RAW_TEXT_SIZE_CLASS.source, "g"));
    for (const item of rawClassMatches) {
      const { line, col } = getLineAndColumn(content, item.index);
      violations.push({
        file,
        line,
        col,
        rule: "raw-text-size-class",
        detail: item.text,
      });
    }

    if (!ALLOWED_FONT_LITERAL_FILES.has(file)) {
      const fontLiteralMatches = collectMatches(content, new RegExp(INLINE_FONT_SIZE_LITERAL.source, "g"));
      for (const item of fontLiteralMatches) {
        const { line, col } = getLineAndColumn(content, item.index);
        violations.push({
          file,
          line,
          col,
          rule: "inline-font-size-literal",
          detail: item.text,
        });
      }
    }
  }

  if (violations.length === 0) {
    console.log("Typography check passed.");
    return;
  }

  console.error(`Typography check failed with ${violations.length} violation(s):`);
  for (const violation of violations) {
    const rel = path.relative(ROOT, violation.file);
    console.error(`- ${rel}:${violation.line}:${violation.col} [${violation.rule}] ${violation.detail}`);
  }
  process.exitCode = 1;
}

main().catch((error) => {
  console.error("Typography check failed unexpectedly.");
  console.error(error);
  process.exitCode = 1;
});
