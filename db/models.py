"""Table definitions. Works on Postgres (Supabase, docker-compose) and SQLite (zero-config local runs).

db/schema.sql is generated from this file: python scripts/dump_schema.py
"""
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    func,
)

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(255), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("plan", String(20), nullable=False, server_default="free"),          # free | premium
    Column("stripe_customer_id", String(255)),
    Column("ntfy_topic", String(100)),
    Column("is_admin", Boolean, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

sites = Table(
    "sites", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("label", String(100)),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    Column("elevation", Float, server_default="0"),
    Column("kwp", Float, nullable=False),
    Column("tilt", Float, nullable=False),
    Column("azimuth", Float, nullable=False),            # compass degrees, 180 = south
    Column("inverter_kw", Float),
    Column("battery_kwh", Float, server_default="0"),
    Column("supplier", String(100)),
    Column("customer_type", String(30), nullable=False, server_default="individual"),
    Column("compensation_type", String(30), nullable=False, server_default="quantity"),
    Column("price_lei_kwh", Float),
    Column("monthly_kwh", Float),                        # typical monthly consumption, fallback profile
    Column("carryover_kwh", Float, server_default="0"),  # credit carried into the current month
    Column("pvgis_annual_kwh", Float),
    Column("pvgis_monthly_json", JSON),
)

readings = Table(
    "readings", metadata,
    Column("site_id", Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),      # UTC, start of the hour
    Column("pv_kwh", Float),
    Column("load_kwh", Float),
    Column("grid_import_kwh", Float),
    Column("grid_export_kwh", Float),
    Column("batt_charge_kwh", Float),
    Column("batt_discharge_kwh", Float),
    Column("soc_pct", Float),
    PrimaryKeyConstraint("site_id", "ts"),
)

weather = Table(
    "weather", metadata,
    Column("lat_r", Float, nullable=False),
    Column("lon_r", Float, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("kind", String(20), nullable=False),                 # forecast | historical
    Column("ghi", Float),
    Column("dni", Float),
    Column("dhi", Float),
    Column("temp_c", Float),
    Column("wind_ms", Float),
    Column("cloud_pct", Float),
    Column("fetched_at", DateTime(timezone=True)),
    PrimaryKeyConstraint("lat_r", "lon_r", "ts", "kind"),
)

forecasts = Table(
    "forecasts", metadata,
    Column("site_id", Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
    Column("run_at", DateTime(timezone=True), nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("pv_p10", Float),
    Column("pv_p50", Float),
    Column("pv_p90", Float),
    Column("pv_physics", Float),
    Column("load_p50", Float),
    Column("model_version", String(50)),
    PrimaryKeyConstraint("site_id", "run_at", "ts"),
)

models = Table(
    "models", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("site_id", Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(20), nullable=False),                 # solar | load
    Column("trained_at", DateTime(timezone=True), server_default=func.now()),
    Column("metrics_json", JSON),
    Column("artifact_path", String(255)),                       # optional: Supabase Storage path
    Column("artifact", LargeBinary),                            # joblib bytes
)

bills = Table(
    "bills", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("site_id", Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
    Column("supplier", String(100)),
    Column("period_start", Date),
    Column("period_end", Date),
    Column("pod", String(50)),
    Column("total_lei", Float),
    Column("vat_rate", Float),
    Column("file_path", String(255)),                           # empty unless the user opts in to keep it
    Column("parse_method", String(20)),                         # pdf_text | ocr
    Column("confidence", Float),
    Column("status", String(20), nullable=False, server_default="draft"),   # draft | confirmed
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

bill_lines = Table(
    "bill_lines", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("bill_id", Integer, ForeignKey("bills.id", ondelete="CASCADE"), nullable=False),
    Column("line_type", String(40), nullable=False),
    Column("label_raw", Text),
    Column("qty_kwh", Float),
    Column("unit_price", Float),
    Column("amount_lei", Float),
    Column("confidence", Float),
    Column("user_confirmed", Boolean, nullable=False, server_default="0"),
)

bill_checks = Table(
    "bill_checks", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("bill_id", Integer, ForeignKey("bills.id", ondelete="CASCADE"), nullable=False),
    Column("check_type", String(40), nullable=False),
    Column("expected", Float),
    Column("actual", Float),
    Column("diff_pct", Float),
    Column("severity", String(20)),                             # ok | info | worth_checking
    Column("message", Text),
)

rules = Table(
    "rules", metadata,
    Column("id", String(80), primary_key=True),
    Column("version", Integer, nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("title", Text),
    Column("applies_to_json", JSON),
    Column("params_json", JSON),
    Column("source", Text),
    Column("source_url", Text),
    Column("summary", Text),
    Column("published_at", DateTime(timezone=True), server_default=func.now()),
)

subscriptions = Table(
    "subscriptions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("stripe_session_id", String(255)),
    Column("status", String(30)),
    Column("current_period_end", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

notifications = Table(
    "notifications", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("type", String(30), nullable=False),                 # rule_change | bill_check | system
    Column("payload_json", JSON),
    Column("sent_at", DateTime(timezone=True), server_default=func.now()),
    Column("delivered", Boolean, nullable=False, server_default="0"),
)

kv = Table(
    "kv", metadata,
    Column("key", String(100), primary_key=True),
    Column("value", Text),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)


# ---------------------------------------------------------------- planner (new tables, so existing databases
# only need create_all, no column migrations)
devices = Table(
    "devices", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("site_id", Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(100), nullable=False),
    Column("kind", String(20), nullable=False),          # schedule | continuous | heating | cooling | ev
    Column("power_w", Float),
    Column("hours_per_day", Float),
    Column("start_hour", Integer),
    Column("days_per_week", Integer),
    Column("months_json", JSON),
    Column("flexible", Boolean, nullable=False, server_default="0"),
    Column("is_new", Boolean, nullable=False, server_default="1"),   # planned (adds to demand) vs already at home
    Column("annual_kwh", Float),
    Column("ev_km_day", Float),
    Column("ev_kwh_100km", Float),
    Column("quantity", Integer, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

plan_settings = Table(
    "plan_settings", metadata,
    Column("site_id", Integer, ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True),
    Column("settings_json", JSON),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)
