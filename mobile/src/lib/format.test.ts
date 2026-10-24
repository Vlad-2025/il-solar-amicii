import assert from 'node:assert/strict';
import { test } from 'node:test';

import { date, dayLabel, hourOf, kwh, lei, monthName, num, parseNum, pct, periodLabel } from './format.ts';

test('Romanian numbers', () => {
  assert.equal(num(1234.5, 2), '1.234,50');
  assert.equal(num(0), '0');
  assert.equal(num(-12.345, 1), '−12,3');
  assert.equal(num(1234567), '1.234.567');
  assert.equal(num(null), '–');
  assert.equal(kwh(450), '450 kWh');
  assert.equal(lei(7.62), '7,62 lei');
  assert.equal(pct(-11.52), '−11,5%');
  assert.equal(pct(3), '+3,0%');
});

test('dates without time-zone drift', () => {
  assert.equal(date('2026-09-30'), '30.09.2026');
  assert.equal(date('2026-10-25T00:00:00+03:00'), '25.10.2026');
  assert.equal(monthName('2026-10-01'), 'octombrie 2026');
  assert.equal(dayLabel('2026-10-25'), 'Dum 25');
  assert.equal(dayLabel('2026-10-26T00:00:00+02:00'), 'Lun 26');
  assert.equal(hourOf('2026-10-26T14:00:00+02:00'), 14);
  assert.equal(periodLabel('2026-09-01', '2026-09-30'), '01.09.2026 – 30.09.2026');
  assert.equal(periodLabel(null, '2026-09-30'), 'perioadă necunoscută');
});

test('parsing what people type', () => {
  assert.equal(parseNum('4,51'), 4.51);
  assert.equal(parseNum('4.51'), 4.51);
  assert.equal(parseNum('1.234,56'), 1234.56);
  assert.equal(parseNum(' 12 '), 12);
  assert.equal(parseNum(''), null);
  assert.equal(parseNum('abc'), null);
});
