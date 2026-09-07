import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { getImageUrl, getJurisdictionObservationImage } from "../services/api";

export function useObservationImage(observationId, imageUrl) {
  const { user } = useAuth() || {};
  const publicUrl = getImageUrl(imageUrl);
  const requestKey = user && observationId ? `${user.id || "user"}:${observationId}` : null;
  const [result, setResult] = useState({ requestKey: null, url: null, failed: false });

  useEffect(() => {
    let active = true;
    let objectUrl = null;

    if (publicUrl || !requestKey) return undefined;

    getJurisdictionObservationImage(observationId)
      .then((url) => {
        if (!active) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        setResult({ requestKey, url, failed: false });
      })
      .catch(() => {
        if (active) setResult({ requestKey, url: null, failed: true });
      });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [observationId, publicUrl, requestKey]);

  if (publicUrl) return { source: publicUrl, loading: false, unavailable: false };
  if (!requestKey) return { source: null, loading: false, unavailable: true };
  if (result.requestKey !== requestKey) return { source: null, loading: true, unavailable: false };
  return {
    source: result.url,
    loading: false,
    unavailable: result.failed || !result.url,
  };
}
