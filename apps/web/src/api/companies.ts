import { apiGet } from "./client";
import type { Detail, Company } from "../types";

export function listCompanies(): Promise<Company[]> {
  return apiGet<Company[]>("/api/v1/companies");
}

export function getCompany(id: number): Promise<Detail> {
  return apiGet<Detail>(`/api/v1/companies/${id}`);
}
