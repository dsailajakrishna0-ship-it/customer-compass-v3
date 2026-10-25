import { useEffect, useState } from "react";
import { getCloudModels } from "../api/chat";
import type { ModelCatalog } from "../types";

const EMPTY_CATALOG: ModelCatalog = { free: [], paid: [] };

/** Loads the OpenRouter free/paid model catalog once on mount. */
export function useCloudModels(): { cloudModels: ModelCatalog } {
  const [cloudModels, setCloudModels] = useState<ModelCatalog>(EMPTY_CATALOG);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const catalog = await getCloudModels();
        if (!cancelled) setCloudModels(catalog);
      } catch {
        /* Cloud model list is optional; the "cloud" provider still works with the server's default model. */
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  return { cloudModels };
}
