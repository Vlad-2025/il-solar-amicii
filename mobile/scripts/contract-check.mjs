// Drives a running API with the same paths and payloads the app sends, and checks every field the
// screens read. Run before a demo:  API_URL=http://localhost:8000 node scripts/contract-check.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const API = (process.env.API_URL || 'http://localhost:8000').replace(/\/+$/, '');
const DEMO_BILL = fileURLToPath(new URL('../../data/demo/factura_demo_2026-09.pdf', import.meta.url));
let token = null;

async function call(method, path, body, isForm = false) {
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body && !isForm) headers['Content-Type'] = 'application/json';
  const res = await fetch(API + path, { method, headers, body: isForm ? body : body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => null);
  return { status: res.status, data };
}

const has = (obj, keys, where) => keys.forEach((k) => assert.ok(k in obj, `${where}: missing "${k}"`));
const steps = [];
const step = async (name, fn) => { await fn(); steps.push(name); console.log(`ok  ${name}`); };

await step('GET /health', async () => assert.equal((await call('GET', '/health')).data.ok, true));

await step('POST /auth/demo -> Session (login.tsx)', async () => {
  const r = await call('POST', '/auth/demo');
  assert.equal(r.status, 200);
  has(r.data, ['token', 'user', 'site', 'needs_onboarding', 'ntfy'], 'session');
  has(r.data.user, ['id', 'email', 'plan', 'premium', 'is_admin'], 'session.user');
  has(r.data.ntfy, ['topic', 'web_url', 'app_url'], 'session.ntfy');
  token = r.data.token;
});

await step('GET /forecast/summary (index.tsx)', async () => {
  const r = await call('GET', '/forecast/summary');
  assert.equal(r.status, 200);
  has(r.data, ['weather_source', 'lead_note', 'daily'], 'summary');
  has(r.data.daily[0], ['date', 'pv'], 'summary.daily[0]');
});

await step('POST /bills multipart (scan.tsx) -> draft (bill/[id].tsx Review)', async () => {
  const fd = new FormData();
  fd.append('file', new Blob([await readFile(DEMO_BILL)], { type: 'application/pdf' }), 'factura.pdf');
  const r = await call('POST', '/bills', fd, true);
  assert.equal(r.status, 200, JSON.stringify(r.data));
  has(r.data, ['id', 'status', 'lines', 'balance', 'warnings', 'validation', 'ocr_confidence', 'premium', 'supplier',
               'period_start', 'period_end', 'total_lei'], 'draft');
  has(r.data.lines[0], ['line_type', 'label', 'label_raw', 'qty_kwh', 'unit_price', 'amount_lei', 'confidence',
                        'needs_review', 'explanation'], 'draft.lines[0]');
  assert.equal(r.data.status, 'draft');
  globalThis.bill = r.data;
});

await step('POST /subscription/demo-unlock (cont.tsx)', async () => {
  const s = await call('GET', '/subscription');
  has(s.data, ['plan', 'premium', 'stripe_configured', 'demo_unlock', 'current_period_end', 'test_card'], 'subscription');
  if (!s.data.premium && s.data.demo_unlock) {
    const r = await call('POST', '/subscription/demo-unlock');
    assert.equal(r.data.user.premium, true);
  }
});

await step('POST /bills/{id}/confirm with edited lines (Review.confirm)', async () => {
  const b = globalThis.bill;
  const lines = b.lines.map((ln) => ({ line_type: ln.line_type, label_raw: ln.label_raw, unit_price: ln.unit_price,
    confidence: ln.confidence, qty_kwh: ln.qty_kwh, amount_lei: ln.amount_lei }));
  const r = await call('POST', `/bills/${b.id}/confirm`, { lines });
  assert.equal(r.status, 200, JSON.stringify(r.data));
  has(r.data, ['why_pay', 'rule', 'checks', 'complaint'], 'confirmed');
  has(r.data.balance, ['consumed', 'delivered', 'compensated', 'billed', 'carryover', 'sentence'], 'balance');
  assert.ok(r.data.checks.some((c) => c.severity === 'worth_checking'), 'expected a flagged check');
  has(r.data.complaint, ['subject', 'body', 'flagged'], 'complaint');
});

await step('POST /bills/{id}/check threshold (Explained.recheck)', async () => {
  const r = await call('POST', `/bills/${globalThis.bill.id}/check`, { threshold_pct: 20 });
  assert.equal(r.status, 200);
  assert.ok(!r.data.checks.some((c) => c.severity === 'worth_checking'));
});

await step('GET /bills (scan.tsx, index.tsx)', async () => {
  const r = await call('GET', '/bills');
  has(r.data[0], ['id', 'supplier', 'period_start', 'period_end', 'total_lei', 'consumed_kwh', 'delivered_kwh',
                  'compensated_kwh', 'flagged'], 'bills[0]');
});

await step('GET /forecast (prognoza.tsx)', async () => {
  const r = await call('GET', '/forecast');
  assert.equal(r.status, 200, JSON.stringify(r.data));
  has(r.data, ['weather_source', 'model_version', 'load_method', 'lead_note', 'hourly', 'daily', 'month',
               'solar_metrics', 'load_metrics'], 'forecast');
  has(r.data.hourly[0], ['ts', 'pv_p10', 'pv_p50', 'pv_p90', 'load_p50'], 'hourly[0]');
  has(r.data.daily[0], ['date', 'pv', 'load', 'self_consumed', 'exported', 'imported'], 'daily[0]');
  has(r.data.month, ['month_start', 'measured_days', 'forecast_days', 'extrapolated_days', 'consumed_kwh',
                     'delivered_kwh', 'compensated_kwh', 'billed_kwh', 'new_carryover_kwh', 'est_lei', 'notes'], 'month');
  has(r.data.solar_metrics, ['nmae_pct_corrected', 'nmae_pct_physics', 'nmae_pct_persistence', 'test_from'], 'metrics');
});

await step('GET /alerts + POST /alerts/demo (alerte.tsx)', async () => {
  const d = await call('POST', '/alerts/demo');
  has(d.data, ['delivered', 'title', 'message'], 'demo alert');
  const r = await call('GET', '/alerts');
  has(r.data, ['current_rule', 'change', 'notifications'], 'alerts');
  has(r.data.current_rule, ['title', 'version', 'effective_from', 'summary', 'verified', 'facts'], 'current_rule');
  has(r.data.change, ['changes', 'impact'], 'change');
  has(r.data.notifications[0], ['id', 'type', 'sent_at', 'delivered', 'title', 'message', 'simulated'], 'notification');
});

await step('GET /readings/summary (cont.tsx)', async () => {
  const r = await call('GET', '/readings/summary');
  has(r.data, ['rows', 'start', 'end', 'has_load', 'has_export'], 'readings summary');
});

await step('Planner: catalog, settings, devices, POST /plan (plan.tsx)', async () => {
  const cat = await call('GET', '/plan/catalog');
  has(cat.data, ['catalog', 'kinds', 'usage_types', 'areas', 'scenarios'], 'catalog');
  has(cat.data.catalog[0], ['key', 'name', 'kind'], 'catalog item');
  const st = await call('GET', '/plan/settings');
  has(st.data, ['area', 'usage_type', 'baseline_mode', 'annual_kwh', 'panel_wp', 'battery_module_kwh', 'max_panels',
                'max_battery_modules', 'price_pv_lei_kwp', 'price_batt_lei_kwh', 'casa_verde_baterii'], 'settings');
  const { key: _k, ...ev } = cat.data.catalog.find((c) => c.key === 'ev');
  const dev = await call('POST', '/devices', { ...ev, is_new: true });
  assert.equal(dev.status, 200, JSON.stringify(dev.data));
  has(dev.data, ['id', 'name', 'kind', 'power_w', 'start_hour', 'days_per_week', 'months', 'flexible', 'is_new',
                 'ev_km_day', 'ev_kwh_100km', 'quantity'], 'device');
  const upd = await call('PUT', `/devices/${dev.data.id}`, { ...dev.data, ev_km_day: 50 });
  assert.equal(upd.data.ev_km_day, 50);
  const plan = await call('POST', '/plan?force=true');
  assert.equal(plan.status, 200, JSON.stringify(plan.data));
  has(plan.data, ['production', 'baseline', 'devices', 'demand_kwh', 'current', 'recommended', 'alternatives',
                  'stop_reasons', 'combinations_tested', 'months_current', 'months_recommended', 'schedule_tips',
                  'costs', 'payback', 'existing_payback', 'limits'], 'plan');
  has(plan.data.recommended, ['kwp', 'battery_kwh', 'bought_kwh', 'sold_kwh', 'self_consumption_pct',
    'self_sufficiency_pct', 'panels_total', 'panels_added', 'battery_modules_total', 'battery_modules_added', 'panel_wp',
    'battery_module_kwh', 'inverter_kw_suggested'], 'recommended');
  has(plan.data.alternatives[0], ['label', 'kwp', 'battery_kwh', 'bought_kwh', 'sold_kwh', 'exchange_kwh',
    'self_sufficiency_pct', 'battery_cycles'], 'alternative');
  has(plan.data.months_recommended[0], ['month', 'bought', 'sold'], 'month');
  has(plan.data.baseline, ['label', 'confidence', 'annual_kwh', 'notes'], 'baseline');
  has(plan.data.costs, ['gross_lei', 'net_lei'], 'costs');
  if (plan.data.payback) has(plan.data.payback, ['scenarios', 'bills_year1', 'battery_replacement_year'], 'payback');
  if (plan.data.schedule_tips.length) has(plan.data.schedule_tips[0], ['name', 'from_hour', 'to_hour', 'solar_kwh_now', 'solar_kwh_after'], 'tip');
  assert.equal((await call('DELETE', `/devices/${dev.data.id}`)).status, 200);
});

await step('DELETE /bills/{id} (Explained.remove)', async () => {
  assert.equal((await call('DELETE', `/bills/${globalThis.bill.id}`)).status, 200);
});

console.log(`\n${steps.length} contract checks passed against ${API}`);
