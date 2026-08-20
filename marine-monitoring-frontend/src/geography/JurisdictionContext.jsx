import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { routeContext } from "../config/navigation";
import { getJurisdiction } from "../services/api";

const JurisdictionContext = createContext(null);

export function JurisdictionProvider({ children }) {
  const location = useLocation();
  const route = routeContext(location.pathname);
  const [state, setState] = useState({ key: null, jurisdiction: null, error: null });

  useEffect(() => {
    if (route.scope !== "country") {
      return;
    }
    let active = true;
    const key = `${route.activeRegion}/${route.activeJurisdiction}`;
    getJurisdiction(route.activeRegion, route.activeJurisdiction)
      .then((jurisdiction) => active && setState({ key, jurisdiction, error: null }))
      .catch((error) => active && setState({ key, jurisdiction: null, error }));
    return () => { active = false; };
  }, [route.activeJurisdiction, route.activeRegion, route.scope]);

  const value = useMemo(() => {
    if (route.scope !== "country") return { ...route, loading: false, jurisdiction: null, error: null };
    const key = `${route.activeRegion}/${route.activeJurisdiction}`;
    return { ...route, ...state, loading: state.key !== key };
  }, [route, state]);
  return <JurisdictionContext.Provider value={value}>{children}</JurisdictionContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useJurisdiction() {
  return useContext(JurisdictionContext);
}
