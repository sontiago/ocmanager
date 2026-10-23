import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatBytes } from "../lib/format";

const HEIGHT = 260;
const GRID = "var(--c-border)";
const AXIS = { fontSize: 12, fill: "var(--c-muted)" };

/** «2026-10-22» → «22.10»: на оси хватает дня и месяца. */
const shortDay = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

const tooltipStyle = {
  background: "var(--c-surface)",
  border: "1px solid var(--c-border)",
  color: "var(--c-text)",
};

export function TrafficChart({
  data,
  inLabel,
  outLabel,
}: {
  data: { day: string; bytes_in: number; bytes_out: number }[];
  inLabel: string;
  outLabel: string;
}) {
  const rows = data.map((d) => ({ day: d.day, [inLabel]: d.bytes_in, [outLabel]: d.bytes_out }));
  return (
    <ResponsiveContainer width="100%" height={HEIGHT}>
      <AreaChart data={rows}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
        <XAxis dataKey="day" tickFormatter={shortDay} tick={AXIS} />
        <YAxis tickFormatter={(v: number) => formatBytes(v)} tick={AXIS} width={70} />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(v: number) => formatBytes(v)}
          labelFormatter={(l: string) => l}
        />
        <Legend />
        <Area type="monotone" dataKey={inLabel} stroke="var(--c-info)" fill="var(--c-info)" fillOpacity={0.25} />
        <Area type="monotone" dataKey={outLabel} stroke="var(--c-accent)" fill="var(--c-accent)" fillOpacity={0.25} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function RevenueChart({
  data,
  currency,
  label,
}: {
  data: { day: string; amounts: Record<string, number> }[];
  currency: string;
  label: string;
}) {
  const rows = data.map((d) => ({ day: d.day, [label]: (d.amounts[currency] ?? 0) / 100 }));
  return (
    <ResponsiveContainer width="100%" height={HEIGHT}>
      <BarChart data={rows}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
        <XAxis dataKey="day" tickFormatter={shortDay} tick={AXIS} />
        <YAxis tick={AXIS} width={70} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => `${v} ${currency}`} />
        <Bar dataKey={label} fill="var(--c-ok)" />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function CountChart({
  data,
  label,
}: {
  data: { day: string; count: number }[];
  label: string;
}) {
  const rows = data.map((d) => ({ day: d.day, [label]: d.count }));
  return (
    <ResponsiveContainer width="100%" height={HEIGHT}>
      <LineChart data={rows}>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
        <XAxis dataKey="day" tickFormatter={shortDay} tick={AXIS} />
        <YAxis allowDecimals={false} tick={AXIS} width={40} />
        <Tooltip contentStyle={tooltipStyle} />
        <Line type="monotone" dataKey={label} stroke="var(--c-accent)" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}
