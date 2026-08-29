export const canPrepareJurisdiction = (item) => item.status === "READY";
export const canApplyJurisdiction = (item) => item.status === "APPROVED" && Boolean(item.preparation_id);
export const selectableJurisdictions = (inventory) => inventory.filter((item) => canPrepareJurisdiction(item) || canApplyJurisdiction(item));
export const scientificStateDescription = (value) => value === "SCIENTIFICALLY_EMPTY" ? "No species science inherited" : value;
