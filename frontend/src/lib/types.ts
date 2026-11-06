// Shapes returned by the master-data API.

export type ItemType = "raw_material" | "packaging" | "wip" | "semi_finished" | "finished";
export const ITEM_TYPES: ItemType[] = ["raw_material", "packaging", "wip", "semi_finished", "finished"];
export const PRODUCIBLE: ItemType[] = ["wip", "semi_finished", "finished"];

export interface Uom {
  id: string; code: string; name_en: string; name_ar: string | null;
  dimension: "mass" | "volume" | "count" | "time" | "energy" | "gas" | "other";
  factor_to_base: number; is_system: boolean; active: boolean;
}

export interface Market { id: string; code: string; name_en: string; name_ar: string | null; currency: string; active: boolean; }

export interface ItemRow {
  id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; stock_uom_id: string;
  stock_uom: string; dosage_form: string | null; active: boolean; active_bom_version: number | null; bom_versions: number;
  updated_at: string;
}

export interface ItemDetail extends ItemRow {
  dispensing_uom_id: string | null; dispensing_uom: string | null; density_kg_per_l: number | null;
  description: string | null; grade: string | null; cleaning_group: string | null;
  lead_time_days: number | null; moq: number | null; safety_stock: number | null; qc_release_days: number | null;
  shelf_life_months: number | null; pack_size: number | null; units_per_shipper: number | null;
  standard_cost: number | null; assay_basis?: "as_is" | "dried"; test_before_sale: boolean; not_stock_controlled?: boolean; release_lead_days: number | null;
  conversions: { id: string; uom_id: string; uom: string; factor: number }[];
  markets: { id: string; market_id: string; market: string; currency: string; max_sellable_per_month: number | null; min_remaining_shelf_pct: number | null; active: boolean }[];
  prices: { id: string; market_id: string; market: string; price: number; currency: string; valid_from: string; valid_to: string | null; created_at: string; current: boolean }[];
  used_in: { id: string; code: string; name_en: string; name_ar: string | null; version: number; status: string }[];
}

export interface BomLine {
  id?: string; line_no?: number; component_item_id: string; component_code?: string; component_name_en?: string;
  component_name_ar?: string | null; component_type?: ItemType; quantity: number | string; uom_id: string; uom?: string;
  assay_compensated: boolean; overage_pct: number | string; is_compensating: boolean; notes?: string | null; component_assay_basis?: "as_is" | "dried";
  component_active_bom?: number | null;
}

export interface Bom {
  id: string; item_id: string; version: number; status: "draft" | "active" | "archived"; valid_from: string | null;
  valid_to: string | null; batch_size: number; batch_uom_id: string; batch_uom: string; yield_pct: number;
  batch_mode: "fixed" | "partial"; min_batch_pct: number | null; notes: string | null; updated_at: string;
  item_code: string; item_name_en: string; item_name_ar: string | null; item_type: ItemType; item_stock_uom_id: string;
  lines: BomLine[];
}

export interface BomListRow {
  id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; active: boolean;
  versions: { id: string; version: number; status: Bom["status"]; valid_from: string | null; batch_size: number; batch_uom: string; lines: number }[];
}

export interface ExplodeNode {
  item_id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; quantity: number; uom: string;
  bom_quantity: number; bom_uom: string; assay_compensated: boolean; overage_pct: number; is_compensating: boolean;
  batches: number | null; bom_version: number | null; children: ExplodeNode[];
}

export interface Resource {
  id: string; site_id: string; code: string; name_en: string; name_ar: string | null;
  type: "machine" | "qc_lab" | "room" | "operator_group"; area: string | null; location: string | null;
  efficiency_pct: number; notes: string | null; active: boolean; routing_count: number;
  dirty_hold_hours: number | null; clean_hold_hours: number | null;
}

export interface Downtime {
  id: string; resource_id: string; resource_code: string; resource_name_en: string; resource_name_ar: string | null;
  starts_at: string; ends_at: string; reason: "maintenance" | "calibration" | "qualification" | "breakdown" | "other"; notes: string | null;
}

export interface StepResource { id?: string; resource_id: string; preferred: boolean; fixed_minutes?: number | null; rate_per_hour?: number | null; }
export interface Step {
  id?: string; key?: string; seq?: number; name: string; time_model: "fixed" | "rate";
  fixed_minutes: number | null; rate_per_hour: number | null; setup_minutes: number; uninterrupted?: boolean; with_previous?: boolean; resources: StepResource[];
}

export interface Shift { id: string; period_id: string | null; weekday: number; name: string; start_time: string; end_time: string; hours: number; }
export interface Period { id: string; name: string; start_date: string; end_date: string; }
export interface Holiday { id: string; date: string; name: string; source: "manual" | "imported"; estimated: boolean; confirmed: boolean; }
export interface CalendarData { year: number; periods: Period[]; shifts: Shift[]; holidays: Holiday[]; imported?: { added: number; source: string; country: string }; }

/** Pick the name in the user's language, falling back to English. */
export function nameOf(x: { name_en: string; name_ar?: string | null }, lang: string) {
  return lang === "ar" && x.name_ar ? x.name_ar : x.name_en;
}
