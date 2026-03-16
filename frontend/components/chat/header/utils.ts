export function getInitials(nameOrEmail: string | undefined): string {
  if (!nameOrEmail) return "?";
  const sanitized = nameOrEmail.trim();
  if (!sanitized) return "?";
  const nameParts = sanitized.split(/\s+/).filter(Boolean);
  if (nameParts.length >= 2) {
    return `${nameParts[0][0]}${nameParts[1][0]}`.toUpperCase();
  }
  if (sanitized.includes("@")) {
    return sanitized.slice(0, 2).toUpperCase();
  }
  return sanitized.slice(0, 2).toUpperCase();
}
