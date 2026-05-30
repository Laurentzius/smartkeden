"use client";

import { useState, useEffect, useCallback } from "react";
import type { ExchangeRates } from "@/types/api";
import { fetchExchangeRates } from "@/lib/api";

const DEFAULT_RATES: ExchangeRates = {
  USD: 450.0,
  EUR: 485.0,
  RUB: 5.0,
  CNY: 62.0,
  KZT: 1.0,
};

export function useExchangeRates() {
  const [rates, setRates] = useState<ExchangeRates>(DEFAULT_RATES);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchExchangeRates();
      setRates(data);
    } catch (e) {
      console.warn("Failed to fetch rates, using cached defaults", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { rates, loading, refresh };
}
