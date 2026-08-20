/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { getCurrentUser, loginTrustedUser, logoutTrustedUser } from "../services/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(sessionStorage.getItem("trustedAccessToken")));

  useEffect(() => {
    if (!sessionStorage.getItem("trustedAccessToken")) return;
    getCurrentUser().then(setUser).catch(() => sessionStorage.removeItem("trustedAccessToken")).finally(() => setLoading(false));
  }, []);

  async function signIn(email, password) {
    const result = await loginTrustedUser(email, password);
    sessionStorage.setItem("trustedAccessToken", result.access_token);
    setUser(result.user);
    return result.user;
  }

  async function signOut() {
    try { await logoutTrustedUser(); } finally { sessionStorage.removeItem("trustedAccessToken"); setUser(null); }
  }

  const value = useMemo(() => ({ user, loading, signIn, signOut }), [user, loading]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

export function jurisdictionRoles(user, region, jurisdiction) {
  if (user?.is_platform_admin) return ["PLATFORM_ADMIN"];
  return user?.authorized_jurisdictions?.find((item) => item.region === region && item.slug === jurisdiction)?.roles || [];
}
