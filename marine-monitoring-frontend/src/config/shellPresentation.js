export function navigationSectionLabel(scope, jurisdictionName) {
  return scope === "country"
    ? `${jurisdictionName || "Jurisdiction"} agency workspace`
    : scope;
}

export function showPlatformAdminReturn(scope, user) {
  return scope === "country" && user?.is_platform_admin === true;
}
