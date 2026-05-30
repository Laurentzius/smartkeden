"use client";

import { useState } from "react";
import type { CalculationRequest, CalculationResponse } from "@/types/api";
import { calculateDuties } from "@/lib/api";

export function useCalculator() {
  const [invoicePrice, setInvoicePrice] = useState<number>(1000);
  const [currency, setCurrency] = useState<string>("USD");
  const [customRate, setCustomRate] = useState<number>(450);
  const [transportCost, setTransportCost] = useState<number>(50000);
  const [dutyRate, setDutyRate] = useState<number>(10);
  const [exciseRate, setExciseRate] = useState<number>(0);
  const [isRecycling, setIsRecycling] = useState<boolean>(false);

  const [result, setResult] = useState<CalculationResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const calculate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const payload: CalculationRequest = {
        invoice_price: Number(invoicePrice),
        currency,
        exchange_rate: Number(customRate),
        transport_to_border: Number(transportCost),
        duty_rate_percent: Number(dutyRate),
        excise_rate_percent: Number(exciseRate),
        excise_specific_rate: 0,
        excise_units_count: 0,
        is_subject_to_recycling_fee: isRecycling,
      };
      const data = await calculateDuties(payload);
      setResult(data);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Ошибка при выполнении расчета",
      );
    } finally {
      setLoading(false);
    }
  };

  /** Auto-populate calculator form from an HS code candidate. */
  const applyCandidate = (duty: number, excise: number, recycling: boolean) => {
    setDutyRate(duty);
    setExciseRate(excise);
    setIsRecycling(recycling);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return {
    // form state
    invoicePrice,
    setInvoicePrice,
    currency,
    setCurrency,
    customRate,
    setCustomRate,
    transportCost,
    setTransportCost,
    dutyRate,
    setDutyRate,
    exciseRate,
    setExciseRate,
    isRecycling,
    setIsRecycling,
    // result state
    result,
    loading,
    error,
    // actions
    calculate,
    applyCandidate,
  };
}
