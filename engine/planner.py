"""System planner: how many panels and batteries make the household trade as little as possible with the grid.

Goal (as defined by the product): use the panels' energy at home, store the excess, and minimise both what
is bought from and what is sold to the grid. Every combination of panels and battery modules added to the
current system (or to none), within the roof and battery limits, is simulated over a year. A combination is
valid when its last components pull their weight:
  * the last panel lowers  bought + sold  (more than half of its energy is used at home or stored);
  * the last battery module lowers  bought + sold  AND really cycles: at least `min_cycles` full cycles a year
    (default 150), otherwise it would mostly sit idle.
The valid combination with the least  bought + sold  is recommended (ties go to the smaller system).
Adding one component at a time is not enough: a few panels can be useless without a battery and vice versa.

Break-even is reported separately, in lei, with three scenarios for the rules after 2030.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from engine import devices as dev_mod
from engine import weather as wx
from engine.demand import baseline, year_index
from engine.solar import Site, physics
from rules.compensation import compute_compensation, rule_for

LOCAL_TZ = "Europe/Bucharest"

# Starting prices, VAT included, checked 25 Oct 2026; sources in README "System planner". They are rough
# market levels: users should replace them with their installer's quote.
DEFAULT_SETTINGS: dict = {
    "area": "urban", "usage_type": "auto", "baseline_mode": "auto", "annual_kwh": None,
    "panel_wp": 450, "battery_module_kwh": 5.0, "max_panels": 30, "max_battery_modules": 4, "min_cycles": 150,
    "price_pv_lei_kwp": 4500.0, "price_batt_lei_kwh": 1200.0, "batt_install_lei": 2000.0,
    "hybrid_retrofit_lei": 5500.0, "hybrid_new_lei": 3500.0, "has_hybrid_inverter": False,
    "subsidy_lei": 0.0, "casa_verde_baterii": False, "price_escalation_pct": 0.0, "post2030_export_share": 0.3,
    "existing_cost_lei": None, "existing_year": None, "horizon_years": 25,
}
SCENARIOS = {
    "current": "Regulile de azi continuă și după 2030",
    "partial": "După 2030 surplusul valorează doar o parte din preț",
    "none": "După 2030 surplusul nu mai valorează nimic (contează doar autoconsumul)",
}
PANEL_DEGRADATION = 0.005
BATTERY_CYCLE_LIFE = 6000
BATTERY_MAX_YEARS = 15


def settings_with_defaults(s: dict | None) -> dict:
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in (s or {}).items() if k in DEFAULT_SETTINGS and v is not None})
    return out


# ---------------------------------------------------------------- production
def production_per_kwp(site: dict, index: pd.DatetimeIndex, readings: pd.DataFrame | None,
                       solar_model=None) -> tuple[pd.Series, pd.Series, dict]:
    """kWh per kWp per hour over the planning year, plus outdoor temperature."""
    from engine.pipeline import historical_weather

    info: dict = {}
    try:
        w = historical_weather(site, index[0].date(), index[-1].date()).reindex(index)
        w = wx.fill_gaps(w)
        info["weather_source"] = ("vremea sintetică a contului demo" if (site.get("label") or "") == "demo"
                                  else "vremea reală din ultimul an (Open-Meteo)")
    except wx.WeatherUnavailable:
        w = wx.clear_sky_weather(site["lat"], site["lon"], index, site.get("elevation") or 0, cloud_factor=0.72)
        info["weather_source"] = "estimare fără vreme reală (cer senin redus cu 28%): rezultatele sunt orientative"
    unit = Site(lat=site["lat"], lon=site["lon"], kwp=1.0, tilt=float(site.get("tilt") or 30),
                azimuth=float(site.get("azimuth") or 180), elevation=float(site.get("elevation") or 0))
    phys = physics(unit, w)
    pv1 = phys["pv_kw"].copy()
    if solar_model is not None:
        pv1 = pv1 * solar_model.ratios(phys)["r50"].where(pv1 > 0, 0.0)
        info["learned_correction"] = True

    kwp = float(site.get("kwp") or 0)
    if kwp > 0 and readings is not None and not readings.empty and readings["pv_kwh"].reindex(index).notna().mean() > 0.9:
        actual = readings["pv_kwh"].reindex(index)
        k = float(actual.sum() / (pv1[actual.notna()] * kwp).sum())
        k = float(np.clip(k, 0.6, 1.3))
        pv1 = pv1 * k
        info["calibrated_to_actual"] = round(k, 3)
    return pv1.clip(lower=0), w["temp_c"], info


# ---------------------------------------------------------------- simulation
@dataclass
class Eval:
    kwp: float
    battery_kwh: float
    pv: float
    load: float
    bought: float
    sold: float
    discharged: float
    imp: np.ndarray
    exp: np.ndarray

    @property
    def exchange(self) -> float:
        return self.bought + self.sold

    @property
    def self_consumption(self) -> float:      # share of solar energy used at home (directly or via battery)
        return (self.pv - self.sold) / self.pv if self.pv > 0 else 0.0

    @property
    def self_sufficiency(self) -> float:      # share of household demand covered by the panels
        return (self.load - self.bought) / self.load if self.load > 0 else 0.0

    @property
    def cycles(self) -> float:
        return self.discharged / self.battery_kwh if self.battery_kwh > 0 else 0.0

    def summary(self) -> dict:
        return {"kwp": round(self.kwp, 2), "battery_kwh": round(self.battery_kwh, 1), "pv_kwh": round(self.pv),
                "load_kwh": round(self.load), "bought_kwh": round(self.bought), "sold_kwh": round(self.sold),
                "exchange_kwh": round(self.exchange), "self_consumption_pct": round(100 * self.self_consumption, 1),
                "self_sufficiency_pct": max(0.0, round(100 * self.self_sufficiency, 1)), "battery_cycles": round(self.cycles)}


def simulate(pv: np.ndarray, load: np.ndarray, cap: float, round_trip: float = 0.9, c_rate: float = 0.5,
             soc_start: float = 0.5) -> tuple[np.ndarray, np.ndarray, float]:
    """Hourly import, export and total battery discharge. Same rules as engine.combine.simulate, faster."""
    direct = np.minimum(pv, load)
    surplus, deficit = pv - direct, load - direct
    if cap <= 0:
        return deficit, surplus, 0.0
    eta = round_trip ** 0.5
    pmax, soc = cap * c_rate, cap * soc_start
    imp, exp = deficit.copy(), surplus.copy()
    disch_total = 0.0
    sur, dfc = surplus.tolist(), deficit.tolist()
    imp_l, exp_l = imp.tolist(), exp.tolist()
    for i in range(len(sur)):
        s = sur[i]
        if s > 0:
            c = min(s, pmax, (cap - soc) / eta)
            soc += c * eta
            exp_l[i] = s - c
        d = dfc[i]
        if d > 0:
            out = min(d, pmax, soc * eta)
            soc -= out / eta
            imp_l[i] = d - out
            disch_total += out
    return np.asarray(imp_l), np.asarray(exp_l), disch_total


def evaluate(pv1: np.ndarray, load: np.ndarray, kwp: float, cap: float) -> Eval:
    pv = pv1 * kwp
    imp, exp, dis = simulate(pv, load, cap)
    return Eval(kwp, cap, float(pv.sum()), float(load.sum()), float(imp.sum()), float(exp.sum()), dis, imp, exp)


def simulate_batch(pv1: np.ndarray, load: np.ndarray, kwps: np.ndarray, caps: np.ndarray,
                   round_trip: float = 0.9, c_rate: float = 0.5, soc_start: float = 0.5):
    """All combinations at once: loop over hours, vectors over combinations. Returns yearly bought, sold,
    battery discharge per combination."""
    eta = round_trip ** 0.5
    pmax = caps * c_rate
    soc = caps * soc_start
    bought = np.zeros(len(kwps))
    sold = np.zeros(len(kwps))
    dis = np.zeros(len(kwps))
    for p1, ld in zip(pv1.tolist(), load.tolist(), strict=True):
        pv = kwps * p1
        direct = np.minimum(pv, ld)
        sur = pv - direct
        dfc = ld - direct
        c = np.minimum(np.minimum(sur, pmax), np.where(caps > 0, (caps - soc) / eta, 0.0))
        soc = soc + c * eta
        out = np.minimum(np.minimum(dfc, pmax), soc * eta)
        soc = soc - out / eta
        sold += sur - c
        bought += dfc - out
        dis += out
    return bought, sold, dis


def optimise(pv1: np.ndarray, load: np.ndarray, base_kwp: float, base_cap: float, s: dict) -> dict:
    """Search every (panels added, battery modules added) within the limits. Valid combinations obey the two
    rules on their last component; the valid one with the least  bought + sold  wins (ties: smaller system)."""
    wp, module = s["panel_wp"] / 1000.0, float(s["battery_module_kwh"])
    cur_panels = int(round(base_kwp / wp)) if base_kwp > 0 else 0
    cur_modules = int(round(base_cap / module)) if base_cap > 0 else 0
    max_add_p = max(0, int(s["max_panels"]) - cur_panels)
    max_add_m = max(0, int(s["max_battery_modules"]) - cur_modules)
    min_through = float(s["min_cycles"]) * module

    grid = [(n, m) for m in range(max_add_m + 1) for n in range(max_add_p + 1)]
    kwps = np.array([base_kwp + n * wp for n, _ in grid])
    caps = np.array([base_cap + m * module for _, m in grid])
    bought, sold, dis = simulate_batch(pv1, load, kwps, caps)
    at = {g: i for i, g in enumerate(grid)}
    exch = bought + sold

    def valid(n, m):
        i = at[(n, m)]
        if n > 0 and not exch[i] < exch[at[(n - 1, m)]] - 1:          # last panel must lower bought + sold
            return False
        if m > 0:
            j = at[(n, m - 1)]
            if not (exch[i] < exch[j] - 1 and dis[i] - dis[j] >= min_through):   # last module must help and cycle
                return False
        return True

    ok = [g for g in grid if valid(*g)]
    best_n, best_m = min(ok, key=lambda g: (round(exch[at[g]]), g[1], g[0]))
    cur = evaluate(pv1, load, base_kwp, base_cap)
    best = evaluate(pv1, load, base_kwp + best_n * wp, base_cap + best_m * module)

    def row(n, m, label):
        i = at[(n, m)]
        total = float(load.sum())
        return {"label": label, "panels_added": n, "modules_added": m, "kwp": round(float(kwps[i]), 2),
                "battery_kwh": round(float(caps[i]), 1), "bought_kwh": round(float(bought[i])),
                "sold_kwh": round(float(sold[i])), "exchange_kwh": round(float(exch[i])),
                "self_sufficiency_pct": max(0.0, round(100 * (total - float(bought[i])) / total, 1)) if total else 0.0,
                "battery_cycles": round(float(dis[i] / caps[i])) if caps[i] > 0 else 0}

    alternatives = [row(0, 0, "Sistemul actual" if base_kwp > 0 else "Fără panouri"), row(best_n, best_m, "Recomandat")]
    stop = []
    if best_n < max_add_p:
        alternatives.append(row(best_n + 1, best_m, "Cu un panou în plus"))
        d = exch[at[(best_n + 1, best_m)]] - exch[at[(best_n, best_m)]]
        stop.append(f"Un panou în plus ar schimba energia cu rețeaua cu {d:+.0f} kWh/an: o parte prea mare din "
                    "producția lui ar fi vândută, nu folosită.")
    else:
        stop.append("Ați atins numărul maxim de panouri setat (spațiul de pe acoperiș).")
    if best_m < max_add_m:
        alternatives.append(row(best_n, best_m + 1, "Cu o baterie în plus"))
        extra = (dis[at[(best_n, best_m + 1)]] - dis[at[(best_n, best_m)]]) / module
        cyc = f"{extra:.0f} " + ("ciclu complet" if round(extra) == 1 else "cicluri complete")
        stop.append(f"Încă un modul de baterie de {module:g} kWh ar fi folosit, el singur, doar cât {cyc} pe an "
                    f"(minim {s['min_cycles']}): ar sta în mare parte nefolosit.")
    else:
        stop.append("Ați atins numărul maxim de baterii setat.")
    if best_n > 0:
        alternatives.append(row(best_n - 1, best_m, "Cu un panou mai puțin"))
    if best_m > 0:
        alternatives.append(row(best_n, best_m - 1, "Cu o baterie mai puțin"))
    return {"current": cur, "best": best, "panels_added": best_n, "modules_added": best_m,
            "alternatives": alternatives, "stop_reasons": stop, "current_panels": cur_panels,
            "current_modules": cur_modules, "combinations_tested": len(grid)}


# ---------------------------------------------------------------- money
def monthly(index: pd.DatetimeIndex, arr: np.ndarray) -> pd.Series:
    local = index.tz_convert(LOCAL_TZ)
    return pd.Series(arr, index=local).resample("MS").sum()


def bill_lei(imp_m: pd.Series, exp_m: pd.Series, price: float, mode: str, share: float, kwp: float,
             customer_type: str) -> float:
    if mode == "none":
        return float(imp_m.sum() * price)
    if mode == "partial":
        return float(np.clip(imp_m.values * price - exp_m.values * share * price, 0, None).sum())
    rule = rule_for(date.today(), customer_type, kwp, _rules())
    carry = 0.0
    billed = 0.0
    for _pass in range(2):                           # second pass starts with the steady-state carry-over
        billed = 0.0
        for ts in imp_m.index:
            end = (ts + pd.offsets.MonthEnd(0)).date()
            res = compute_compensation((ts.date(), end), imp_m[ts], exp_m[ts], carry, rule, kwp)
            billed += res.billed_kwh
            carry = res.new_carryover_kwh
    return float(billed * price)


def _rules():
    from engine.pipeline import all_rules
    return all_rules()


def costs(base_kwp: float, base_cap: float, add_kwp: float, add_cap: float, s: dict) -> dict:
    panels = add_kwp * s["price_pv_lei_kwp"]
    battery = add_cap * s["price_batt_lei_kwh"] + (s["batt_install_lei"] if add_cap > 0 else 0.0)
    inverter = 0.0
    if add_cap > 0 and base_cap <= 0 and not s["has_hybrid_inverter"]:
        inverter = s["hybrid_retrofit_lei"] if base_kwp > 0 else s["hybrid_new_lei"]
    subsidy = float(s["subsidy_lei"] or 0)
    casa_verde = 0.0
    if s["casa_verde_baterii"] and add_cap > 0 and (base_cap + add_cap) >= 10:
        eligible = min(battery, 1500.0 * add_cap)                # AFM cost cap: 1,500 lei/kWh, VAT included
        casa_verde = min(15000.0, 0.75 * eligible)
    gross = panels + battery + inverter
    return {"panels_lei": round(panels), "battery_lei": round(battery), "inverter_lei": round(inverter),
            "gross_lei": round(gross), "subsidy_lei": round(subsidy + casa_verde), "casa_verde_lei": round(casa_verde),
            "net_lei": round(max(0.0, gross - subsidy - casa_verde))}


def payback(index, base: Eval, plan: Eval, invest: float, battery_cost: float, price: float, s: dict,
            customer_type: str, start_year: int | None = None) -> dict:
    start_year = start_year or date.today().year
    bi, be = monthly(index, base.imp), monthly(index, base.exp)
    pi, pe = monthly(index, plan.imp), monthly(index, plan.exp)
    share, esc = float(s["post2030_export_share"]), float(s["price_escalation_pct"]) / 100.0
    added_cap = plan.battery_kwh - base.battery_kwh
    replace_year = None
    if added_cap > 0:
        life = min(BATTERY_MAX_YEARS, BATTERY_CYCLE_LIFE / max(plan.cycles, 1.0))
        replace_year = int(np.ceil(life))
    bills = {}
    for mode in ("current", "partial", "none"):
        bills[mode] = (bill_lei(bi, be, price, mode, share, base.kwp, customer_type),
                       bill_lei(pi, pe, price, mode, share, plan.kwp, customer_type))
    out = {}
    for scen in SCENARIOS:
        cum, series, pb = 0.0, [], None
        for y in range(int(s["horizon_years"])):
            year = start_year + y
            mode = "current" if year <= 2030 else scen
            b_base, b_plan = bills[mode]
            saving = (b_base - b_plan) * (1 - PANEL_DEGRADATION) ** y * (1 + esc) ** y
            if replace_year and y == replace_year:
                saving -= battery_cost
            prev = cum
            cum += saving
            series.append(round(cum))
            if pb is None and invest > 0 and cum >= invest:
                pb = y + (invest - prev) / saving if saving > 0 else y + 1
        out[scen] = {"label": SCENARIOS[scen], "payback_years": round(pb, 1) if pb is not None else None,
                     "cumulative_lei": series, "saving_year1_lei": round(bills["current"][0] - bills["current"][1]),
                     "saving_after_2030_lei": round(bills[scen][0] - bills[scen][1])}
    return {"scenarios": out, "bills_year1": {"before_lei": round(bills["current"][0]), "after_lei": round(bills["current"][1])},
            "battery_replacement_year": replace_year, "start_year": start_year}


# ---------------------------------------------------------------- everything together
def plan(site: dict, settings: dict | None, device_list: list[dict], readings: pd.DataFrame | None,
         bills: list[dict], solar_model=None, index: pd.DatetimeIndex | None = None) -> dict:
    s = settings_with_defaults(settings)
    index = index if index is not None else year_index()
    pv1, temp, prod_info = production_per_kwp(site, index, readings, solar_model)
    base_load, base_info = baseline(index, site, s, readings, bills, device_list, temp)
    new_load, device_rows = dev_mod.total_load(device_list, index, temp, only_new=s["baseline_mode"] != "devices")
    if s["baseline_mode"] == "devices":
        new_load = new_load * 0.0                        # already inside the baseline
    load = (base_load + new_load).to_numpy()

    base_kwp, base_cap = float(site.get("kwp") or 0), float(site.get("battery_kwh") or 0)
    opt = optimise(pv1.to_numpy(), load, base_kwp, base_cap, s)
    cur, best = opt["current"], opt["best"]

    surplus = pd.Series(pv1.to_numpy() * best.kwp - load, index=index)
    tips = dev_mod.suggest_schedule(device_list, index, surplus, temp)

    price = site.get("price_lei_kwh")
    add_kwp, add_cap = best.kwp - base_kwp, best.battery_kwh - base_cap
    c = costs(base_kwp, base_cap, add_kwp, add_cap, s)
    money = None
    if price:
        money = payback(index, cur, best, c["net_lei"], c["battery_lei"], float(price), s,
                        site.get("customer_type") or "individual")
    existing = None
    if price and base_kwp > 0 and s.get("existing_cost_lei") and s.get("existing_year"):
        hist = base_load.to_numpy()                      # today's demand, without the planned devices
        none, now = evaluate(pv1.to_numpy(), hist, 0.0, 0.0), evaluate(pv1.to_numpy(), hist, base_kwp, base_cap)
        yr = int(s["existing_year"])
        pb = payback(index, none, now, float(s["existing_cost_lei"]), 0.0, float(price), s,
                     site.get("customer_type") or "individual", start_year=yr)
        existing = {"installed": yr, "cost_lei": float(s["existing_cost_lei"]),
                    "payback_years": {k: v["payback_years"] for k, v in pb["scenarios"].items()},
                    "saving_year_lei": pb["scenarios"]["current"]["saving_year1_lei"]}

    def months(e: Eval):
        df = pd.DataFrame({"pv": monthly(index, pv1.to_numpy() * e.kwp), "load": monthly(index, load),
                           "bought": monthly(index, e.imp), "sold": monthly(index, e.exp)})
        return [{"month": ts.strftime("%Y-%m"), **{k: round(float(v), 1) for k, v in row.items()}} for ts, row in df.iterrows()]

    return {
        "settings": s,
        "period": {"from": index[0].tz_convert(LOCAL_TZ).date().isoformat(),
                   "to": (index[-1].tz_convert(LOCAL_TZ)).date().isoformat()},
        "production": {**prod_info, "kwh_per_kwp_year": round(float(pv1.sum()), 0)},
        "baseline": base_info,
        "devices": device_rows,
        "demand_kwh": round(float(load.sum())),
        "current": {**cur.summary(), "panels": opt["current_panels"], "battery_modules": opt["current_modules"]},
        "recommended": {**best.summary(), "panels_total": opt["current_panels"] + opt["panels_added"],
                        "panels_added": opt["panels_added"], "battery_modules_total": opt["current_modules"] + opt["modules_added"],
                        "battery_modules_added": opt["modules_added"], "panel_wp": s["panel_wp"],
                        "battery_module_kwh": s["battery_module_kwh"],
                        "inverter_kw_suggested": round(max(best.kwp, base_kwp) * 1.0, 1)},
        "alternatives": opt["alternatives"], "stop_reasons": opt["stop_reasons"],
        "combinations_tested": opt["combinations_tested"],
        "months_current": months(cur), "months_recommended": months(best),
        "schedule_tips": tips,
        "costs": c, "payback": money, "existing_payback": existing,
        "price_lei_kwh": price,
        "limits": _limits(best, base_info, money is None, "estimare" not in prod_info["weather_source"]),
    }


def _limits(best: Eval, base_info: dict, no_price: bool, weather_real: bool) -> list[str]:
    out = []
    if best.bought > 0:
        out.append("Iarna producția scade mult, iar bateriile mută energia doar de la o zi la alta, nu de la vară la iarnă: "
                   "o parte din consum se cumpără oricum din rețea.")
    if best.sold > 0:
        out.append("Vara, la prânz, panourile produc mai mult decât poate folosi sau stoca o gospodărie: un surplus rămâne.")
    out.append("Sub compensarea cantitativă lunară de azi, bateriile economisesc puțini bani până în 2030: surplusul "
               "trimis ziua compensează deja consumul de seara. Bateriile se justifică prin autonomie și prin regulile de după 2030.")
    if not weather_real:
        out.append("Fără vremea reală (serviciul meteo indisponibil) iarna pare mai însorită decât este: "
                   "planul supraestimează acoperirea din panouri. Recalculați când serviciul răspunde.")
    if base_info["source"] in ("assumption", "profile"):
        out.append("Consumul de bază este estimat, nu măsurat: încărcați facturi sau exportul invertorului pentru un plan precis.")
    if no_price:
        out.append("Adăugați în profil prețul pe kWh din contract ca să calculăm amortizarea.")
    return out
