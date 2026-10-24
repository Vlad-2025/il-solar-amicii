import { useState } from 'react';
import { Text, View, type LayoutChangeEvent } from 'react-native';
import Svg, { G, Line, Path, Rect, Text as SvgText } from 'react-native-svg';

import { dayLabel, hourOf, num } from '@/lib/format';
import type { DayPoint, HourPoint } from '@/lib/types';

import { C } from './ui';

const PAD = { l: 34, r: 8, t: 10, b: 24 };

const FONT = 'sans-serif';

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((x) => n <= x) ?? 10;
  return step * p;
}

const tick = (t: number) => num(t, Number.isInteger(t) ? 0 : 1);

/** Width from the parent's layout (never negative, works the same on Android and web). */
function useWidth(): [number, (e: LayoutChangeEvent) => void] {
  const [w, setW] = useState(0);
  return [w, (e) => setW(Math.round(e.nativeEvent.layout.width))];
}

function linePath(xs: number[], ys: (number | null | undefined)[], y: (v: number) => number): string {
  let d = '';
  let pen = false;
  ys.forEach((v, i) => {
    if (v === null || v === undefined) {
      pen = false;
      return;
    }
    d += `${pen ? 'L' : 'M'}${xs[i].toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  });
  return d;
}

/** Hourly PV (line + P10–P90 band) and household load (dashed) for the next days. */
export function HourlyChart({ data, height = 220 }: { data: HourPoint[]; height?: number }) {
  const [width, onLayout] = useWidth();
  if (!data.length) return null;
  if (width < 120) return <View onLayout={onLayout} style={{ height }} />;
  const vals = data.flatMap((d) => [d.pv_p90 ?? d.pv_p50 ?? 0, d.load_p50 ?? 0]);
  const yMax = niceMax(Math.max(...vals));
  const iw = width - PAD.l - PAD.r;
  const ih = height - PAD.t - PAD.b;
  const xs = data.map((_, i) => PAD.l + (i / Math.max(data.length - 1, 1)) * iw);
  const y = (v: number) => PAD.t + ih - (v / yMax) * ih;
  const hasBand = data.some((d) => d.pv_p10 !== null && d.pv_p10 !== undefined);

  let band = '';
  if (hasBand) {
    const top = data.map((d, i) => `${xs[i].toFixed(1)},${y(d.pv_p90 ?? 0).toFixed(1)}`);
    const bottom = data.map((d, i) => `${xs[i].toFixed(1)},${y(d.pv_p10 ?? 0).toFixed(1)}`).reverse();
    band = `M${top.join('L')}L${bottom.join('L')}Z`;
  }
  const midnights = data.map((d, i) => ({ i, d })).filter(({ d }) => hourOf(d.ts) === 0);
  const ticks = [0, yMax / 2, yMax];

  return (
    <View style={{ gap: 6 }} onLayout={onLayout}>
      <Svg width={width} height={height}>
        {ticks.map((t) => (
          <G key={t}>
            <Line x1={PAD.l} x2={width - PAD.r} y1={y(t)} y2={y(t)} stroke={C.border} strokeWidth={1} />
            <SvgText x={PAD.l - 4} y={y(t) + 4} fontSize={10} fontFamily={FONT} fill={C.muted} textAnchor="end">{tick(t)}</SvgText>
          </G>
        ))}
        {midnights.map(({ i, d }) => (
          <G key={d.ts}>
            <Line x1={xs[i]} x2={xs[i]} y1={PAD.t} y2={PAD.t + ih} stroke={C.border} strokeWidth={1} />
            <SvgText x={xs[i] + 3} y={height - 8} fontSize={10} fontFamily={FONT} fill={C.muted}>{dayLabel(d.ts)}</SvgText>
          </G>
        ))}
        {hasBand ? <Path d={band} fill={C.pvBand} opacity={0.6} /> : null}
        <Path d={linePath(xs, data.map((d) => d.pv_p50), y)} stroke={C.pv} strokeWidth={2} fill="none" />
        <Path d={linePath(xs, data.map((d) => d.load_p50), y)} stroke={C.load} strokeWidth={1.5} strokeDasharray="4 3" fill="none" />
      </Svg>
      <Legend items={[[C.pv, 'Producție (kWh/oră)'], [C.load, 'Consum'], ...(hasBand ? [[C.pvBand, 'P10–P90 (fără eroarea meteo)'] as [string, string]] : [])]} />
    </View>
  );
}

/** Grouped daily bars. series: [key, label, color] */
export function DailyBars({ data, series, height = 200 }: {
  data: DayPoint[]; series: [keyof DayPoint, string, string][]; height?: number;
}) {
  const [width, onLayout] = useWidth();
  if (!data.length) return null;
  if (width < 120) return <View onLayout={onLayout} style={{ height }} />;
  const yMax = niceMax(Math.max(...data.flatMap((d) => series.map(([k]) => Number(d[k] ?? 0)))));
  const iw = width - PAD.l - PAD.r;
  const ih = height - PAD.t - PAD.b;
  const slot = iw / data.length;
  const bw = Math.max(4, (slot * 0.75) / series.length);
  const y = (v: number) => PAD.t + ih - (v / yMax) * ih;
  return (
    <View style={{ gap: 6 }} onLayout={onLayout}>
      <Svg width={width} height={height}>
        {[0, yMax / 2, yMax].map((t) => (
          <G key={t}>
            <Line x1={PAD.l} x2={width - PAD.r} y1={y(t)} y2={y(t)} stroke={C.border} strokeWidth={1} />
            <SvgText x={PAD.l - 4} y={y(t) + 4} fontSize={10} fontFamily={FONT} fill={C.muted} textAnchor="end">{tick(t)}</SvgText>
          </G>
        ))}
        {data.map((d, i) => {
          const x0 = PAD.l + i * slot + (slot - bw * series.length) / 2;
          return (
            <G key={d.date}>
              {series.map(([k, , color], j) => {
                const v = Number(d[k] ?? 0);
                return <Rect key={String(k)} x={x0 + j * bw} y={y(v)} width={bw - 1} height={Math.max(0, PAD.t + ih - y(v))} fill={color} rx={2} />;
              })}
              <SvgText x={PAD.l + i * slot + slot / 2} y={height - 8} fontSize={10} fontFamily={FONT} fill={C.muted} textAnchor="middle">
                {dayLabel(d.date)}
              </SvgText>
            </G>
          );
        })}
      </Svg>
      <Legend items={series.map(([, label, color]) => [color, label])} />
    </View>
  );
}

function Legend({ items }: { items: [string, string][] }) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
      {items.map(([color, label]) => (
        <View key={label} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <View style={{ width: 12, height: 12, borderRadius: 3, backgroundColor: color }} />
          <Text style={{ fontSize: 12, color: C.muted }}>{label}</Text>
        </View>
      ))}
    </View>
  );
}

/** Grouped bars with ready-made labels (e.g. months). rows[i].values[j] belongs to series[j]. */
export function GroupedBars({ rows, series, height = 190 }: {
  rows: { label: string; values: number[] }[]; series: [string, string][]; height?: number;
}) {
  const [width, onLayout] = useWidth();
  if (!rows.length) return null;
  if (width < 120) return <View onLayout={onLayout} style={{ height }} />;
  const yMax = niceMax(Math.max(...rows.flatMap((r) => r.values)));
  const iw = width - PAD.l - PAD.r;
  const ih = height - PAD.t - PAD.b;
  const slot = iw / rows.length;
  const bw = Math.max(2, (slot * 0.8) / series.length);
  const y = (v: number) => PAD.t + ih - (v / yMax) * ih;
  return (
    <View style={{ gap: 6 }} onLayout={onLayout}>
      <Svg width={width} height={height}>
        {[0, yMax / 2, yMax].map((t) => (
          <G key={t}>
            <Line x1={PAD.l} x2={width - PAD.r} y1={y(t)} y2={y(t)} stroke={C.border} strokeWidth={1} />
            <SvgText x={PAD.l - 4} y={y(t) + 4} fontSize={10} fontFamily={FONT} fill={C.muted} textAnchor="end">{tick(t)}</SvgText>
          </G>
        ))}
        {rows.map((r, i) => {
          const x0 = PAD.l + i * slot + (slot - bw * series.length) / 2;
          return (
            <G key={`${r.label}-${i}`}>
              {r.values.map((v, j) => (
                <Rect key={j} x={x0 + j * bw} y={y(v)} width={bw - 1} height={Math.max(0, PAD.t + ih - y(v))}
                  fill={series[j][1]} rx={1.5} />
              ))}
              <SvgText x={PAD.l + i * slot + slot / 2} y={height - 8} fontSize={9} fontFamily={FONT} fill={C.muted}
                textAnchor="middle">{r.label}</SvgText>
            </G>
          );
        })}
      </Svg>
      <Legend items={series.map(([label, color]) => [color, label] as [string, string])} />
    </View>
  );
}
