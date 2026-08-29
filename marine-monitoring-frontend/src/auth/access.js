export function hasProtectedAccess(user, access, roles = []) {
  if (!user) return false;
  if (access === "admin") return Boolean(user.is_platform_admin);
  if (access === "observation-review") return Boolean(user.is_platform_admin || user.operational_review?.enabled);
  if (access === "scientific-review") return Boolean(user.is_platform_admin || user.scientific_review?.enabled);
  if (user.is_platform_admin) return true;
  if (access === "investigations") return roles.some((role) => ["VIEWER", "REVIEWER", "MANAGER"].includes(role));
  return roles.some((role) => ["REVIEWER", "MANAGER"].includes(role));
}
