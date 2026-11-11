export type User = {
  id: string;
  email: string;
  display_name: string;
  role: "admin" | "user";
  active?: boolean;
  created_at?: string;
  last_login_at?: string | null;
};

export type Transaction = {
  id: string;
  date: string;
  description: string;
  merchant?: string | null;
  merchant_id?: string | null;
  amount_inr: number;
  original_amount?: number | null;
  currency: string;
  person: "Me" | "Wife" | "Unknown" | string;
  kind: "Purchase" | "Refund" | "Card payment" | "Fee" | "Interest" | "Other" | string;
  allocation: string;
  share_percent: number;
  owed_inr: number;
  payment_method: string;
  category: string;
  statement_id?: string | null;
  statement_month?: string | null;
  bank?: string | null;
  card_name?: string | null;
  notes?: string;
  source_page?: number | null;
  source_bbox?: number[] | null;
  ocr_confidence?: number | null;
  ocr_amount_confidence?: number | null;
  ocr_amount_match?: number | null;
  suggested_allocation?: string | null;
  suggestion_reason?: string | null;
};

export type Statement = {
  id: string;
  filename: string;
  bank: string;
  card_name: string;
  period: string;
  statement_month?: string | null;
  uploaded_at: string;
  extraction_status?: string;
  transaction_count?: number;
  expected_charges_inr?: number | null;
  extracted_charges_inr?: number | null;
  reconciliation_difference_inr?: number | null;
  reconciliation_status?: string;
};

export type Merchant = {
  id: string;
  display_name: string;
  legal_name?: string;
  aliases: string[];
  category: string;
  allocation_suggestion?: string;
  suggestion_person?: string;
};

export type DiscoveryResult = {
  type?: string;
  title: string;
  description?: string;
  url?: string;
  match_score?: number;
  merchant_id?: string;
  suggested_brand_name?: string;
  suggested_legal_name?: string;
};

export type MerchantDiscovery = {
  id: string;
  raw_alias: string;
  query_alias: string;
  transaction_count: number;
  statement_ids: string[];
  status: string;
  results: DiscoveryResult[];
  search_error?: string;
  search_query?: string;
  searched_at?: string;
};

export type Backup = {
  name: string;
  size_bytes: number;
  created_at: string;
};

export type BackupStatus = {
  configured: boolean;
  interval_hours?: number;
  retention_count?: number;
  backups: Backup[];
  latest?: Backup | null;
};

export type AuthState = {
  auth_required: boolean;
  authenticated: boolean;
  user: User | null;
  csrf_token: string;
};
