// Romanian number and date formatting done by hand: Hermes' Intl support for "ro-RO" varies by device.

export function num(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return '–';
  const fixed = Math.abs(x).toFixed(digits);
  const [int, dec] = fixed.split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return (x < 0 ? '−' : '') + grouped + (dec ? ',' + dec : '');
}

export const kwh = (x: number | null | undefined, digits = 0) => `${num(x, digits)} kWh`;
export const lei = (x: number | null | undefined) => `${num(x, 2)} lei`;
export const pct = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined ? '–' : `${x > 0 ? '+' : ''}${num(x, digits)}%`;

const MONTHS = ['ianuarie', 'februarie', 'martie', 'aprilie', 'mai', 'iunie', 'iulie', 'august', 'septembrie',
  'octombrie', 'noiembrie', 'decembrie'];
const DAYS = ['Dum', 'Lun', 'Mar', 'Mie', 'Joi', 'Vin', 'Sâm'];

/** "2026-09-30" or an ISO timestamp -> "30.09.2026" (date part only, no time zone shifts). */
export function date(iso: string | null | undefined): string {
  if (!iso) return '–';
  const [y, m, d] = iso.slice(0, 10).split('-');
  return `${d}.${m}.${y}`;
}

export function monthName(iso: string): string {
  const [y, m] = iso.slice(0, 10).split('-').map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

/** "2026-10-25" -> "Dum 25" (weekday computed in UTC from the calendar date, so no TZ drift). */
export function dayLabel(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${DAYS[wd]} ${String(d).padStart(2, '0')}`;
}

/** Hour of day from an ISO timestamp that already carries the Romanian offset ("...T14:00:00+03:00"). */
export function hourOf(iso: string): number {
  return Number(iso.slice(11, 13));
}

export function periodLabel(start?: string | null, end?: string | null): string {
  if (!start || !end) return 'perioadă necunoscută';
  return `${date(start)} – ${date(end)}`;
}

/** "4,51" and "4.51" both mean 4.51; with a comma present, dots are thousands separators ("1.234,56"). */
export const parseNum = (s: string): number | null => {
  const t = s.trim();
  if (!t) return null;
  const v = Number(t.includes(',') ? t.replace(/\./g, '').replace(',', '.') : t);
  return Number.isFinite(v) ? v : null;
};

