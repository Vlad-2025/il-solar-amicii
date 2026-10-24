export type Site = {
  id: number;
  label?: string | null;
  lat: number;
  lon: number;
  elevation?: number | null;
  kwp: number;
  tilt: number;
  azimuth: number;
  inverter_kw?: number | null;
  battery_kwh?: number | null;
  supplier?: string | null;
  customer_type: string;
  compensation_type: string;
  price_lei_kwh?: number | null;
  monthly_kwh?: number | null;
  carryover_kwh?: number | null;
  pvgis_annual_kwh?: number | null;
};

export type Me = {
  user: { id: number; email: string; plan: string; premium: boolean; is_admin: boolean };
  site: Site | null;
  needs_onboarding: boolean;
  ntfy: { topic: string | null; web_url: string | null; app_url: string | null };
};

export type Session = Me & { token: string };

export type BillLine = {
  id?: number;
  line_type: string;
  label: string;
  label_raw?: string | null;
  qty_kwh?: number | null;
  unit_price?: number | null;
  amount_lei?: number | null;
  confidence?: number | null;
  needs_review?: boolean;
  explanation?: string;
};

export type Check = {
  check_type: string;
  expected?: number | null;
  actual?: number | null;
  diff_pct?: number | null;
  severity: 'ok' | 'info' | 'worth_checking' | string;
  message: string;
};

export type Bill = {
  id: number;
  status: 'draft' | 'confirmed';
  supplier?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  pod?: string | null;
  total_lei?: number | null;
  vat_rate?: number | null;
  confidence?: number | null;
  parse_method?: string | null;
  lines: BillLine[];
  balance: { consumed?: number | null; delivered?: number | null; compensated?: number | null;
             billed?: number | null; carryover?: number | null; sentence: string };
  why_pay?: string | null;
  rule?: { label: string; verified: boolean } | null;
  premium: boolean;
  checks?: Check[] | null;
  complaint?: { subject: string; body: string; flagged: number } | null;
  warnings?: string[];
  validation?: { ok: boolean; message: string }[];
  ocr_confidence?: number | null;
};

export type BillSummary = {
  id: number;
  supplier?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  total_lei?: number | null;
  consumed_kwh?: number | null;
  delivered_kwh?: number | null;
  compensated_kwh?: number | null;
  flagged: number;
};

export type HourPoint = {
  ts: string;
  pv_p10?: number | null;
  pv_p50?: number | null;
  pv_p90?: number | null;
  load_p50?: number | null;
  exported?: number | null;
  imported?: number | null;
};

export type DayPoint = { date: string; pv: number; load?: number; self_consumed?: number; exported?: number; imported?: number };

export type MonthEstimate = {
  month_start: string;
  month_end: string;
  measured_days: number;
  forecast_days: number;
  extrapolated_days: number;
  consumed_kwh: number;
  delivered_kwh: number;
  compensated_kwh: number;
  billed_kwh: number;
  new_carryover_kwh: number;
  est_lei?: number | null;
  notes: string[];
};

export type Forecast = {
  weather_source: string;
  model_version: string;
  load_method: string;
  lead_note: string;
  hourly: HourPoint[];
  daily: DayPoint[];
  month: MonthEstimate;
  solar_metrics?: Record<string, number | string> | null;
  load_metrics?: Record<string, number | string> | null;
};

export type ForecastSummary = { weather_source: string; lead_note: string; daily: DayPoint[] };

export type Alerts = {
  current_rule: null | {
    title: string;
    version: number;
    effective_from: string;
    summary: string;
    verified: boolean;
    source?: string | null;
    source_url?: string | null;
    facts: [string, string][];
  };
  change: null | { changes: string[]; impact: string };
  notifications: {
    id: number;
    type: string;
    sent_at?: string | null;
    delivered: boolean;
    title?: string | null;
    message?: string | null;
    simulated: boolean;
  }[];
};

export type Subscription = {
  plan: string;
  premium: boolean;
  stripe_configured: boolean;
  demo_unlock: boolean;
  current_period_end?: string | null;
  test_card: string;
};

export type Device = {
  id?: number;
  name: string;
  kind: 'schedule' | 'continuous' | 'heating' | 'cooling' | 'ev' | string;
  power_w?: number | null;
  hours_per_day?: number | null;
  start_hour?: number | null;
  days_per_week?: number | null;
  months?: number[];
  flexible?: boolean;
  is_new?: boolean;
  annual_kwh?: number | null;
  ev_km_day?: number | null;
  ev_kwh_100km?: number | null;
  quantity?: number;
};

export type CatalogItem = Device & { key: string };

export type PlanSettings = {
  area: 'urban' | 'rural' | string;
  usage_type: 'auto' | 'standard' | 'day' | 'night' | string;
  baseline_mode: 'auto' | 'devices' | string;
  annual_kwh?: number | null;
  panel_wp: number;
  battery_module_kwh: number;
  max_panels: number;
  max_battery_modules: number;
  min_cycles: number;
  price_pv_lei_kwp: number;
  price_batt_lei_kwh: number;
  casa_verde_baterii: boolean;
  [k: string]: unknown;
};

export type PlanCatalog = {
  catalog: CatalogItem[];
  kinds: Record<string, string>;
  usage_types: Record<string, string>;
  areas: Record<string, string>;
  scenarios: Record<string, string>;
};

export type PlanSystem = {
  kwp: number; battery_kwh: number; pv_kwh: number; load_kwh: number; bought_kwh: number; sold_kwh: number;
  exchange_kwh: number; self_consumption_pct: number; self_sufficiency_pct: number; battery_cycles: number;
};

export type Plan = {
  period: { from: string; to: string };
  production: { weather_source: string; kwh_per_kwp_year: number };
  baseline: { source: string; label: string; confidence: string; annual_kwh: number; notes: string[] };
  devices: { id?: number | null; name: string; kind: string; annual_kwh: number; is_new: boolean; flexible: boolean }[];
  demand_kwh: number;
  current: PlanSystem & { panels: number; battery_modules: number };
  recommended: PlanSystem & { panels_total: number; panels_added: number; battery_modules_total: number;
    battery_modules_added: number; panel_wp: number; battery_module_kwh: number; inverter_kw_suggested: number };
  alternatives: { label: string; kwp: number; battery_kwh: number; bought_kwh: number; sold_kwh: number;
    exchange_kwh: number; self_sufficiency_pct: number; battery_cycles: number }[];
  stop_reasons: string[];
  combinations_tested: number;
  months_current: { month: string; pv: number; load: number; bought: number; sold: number }[];
  months_recommended: { month: string; pv: number; load: number; bought: number; sold: number }[];
  schedule_tips: { id?: number | null; name: string; from_hour: number; to_hour: number; solar_kwh_now: number;
    solar_kwh_after: number; gain_kwh: number }[];
  costs: { panels_lei: number; battery_lei: number; inverter_lei: number; gross_lei: number; subsidy_lei: number; net_lei: number };
  payback: null | {
    scenarios: Record<string, { label: string; payback_years: number | null; saving_year1_lei: number;
      saving_after_2030_lei: number; cumulative_lei: number[] }>;
    bills_year1: { before_lei: number; after_lei: number };
    battery_replacement_year: number | null;
    start_year: number;
  };
  existing_payback: null | { installed: number; cost_lei: number; saving_year_lei: number;
    payback_years: Record<string, number | null> };
  limits: string[];
};
