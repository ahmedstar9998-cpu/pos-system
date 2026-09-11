"""Migrate a SHAKWEER NET SQLite database into the PostgreSQL schema.
Usage:
  set DATABASE_URL=postgresql+psycopg://...
  python scripts/migrate_sqlite_to_postgres.py C:\\path\\shakweer_net.db
"""
import sys,sqlite3,os
from pathlib import Path
from sqlalchemy import create_engine,text
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import init_schema,engine,SessionLocal
if len(sys.argv)!=2: raise SystemExit('Usage: python scripts/migrate_sqlite_to_postgres.py PATH_TO_SQLITE_DB')
src=Path(sys.argv[1]).expanduser().resolve()
if not src.exists(): raise SystemExit(f'File not found: {src}')
con=sqlite3.connect(src); con.row_factory=sqlite3.Row
with engine.begin() as c:
    # Import in dependency order. Existing IDs are preserved where possible.
    tables=['settings','users','categories','products','customers','sales_invoices','sales_items','cash_transactions','customer_payments','maintenance_tickets','maintenance_parts','maintenance_payments','expenses','employees','attendance','weekly_wages','payroll','cashier_advances','net_faults','daily_orders','product_returns','whatsapp_messages','audit_logs']
    for t in tables:
        cols=[r[1] for r in con.execute(f'PRAGMA table_info({t})').fetchall()]
        if not cols: continue
        rows=con.execute(f'SELECT {",".join(cols)} FROM {t}').fetchall()
        if not rows: continue
        # Only insert columns that exist in target; source legacy schemas can have extra columns.
        target_cols={r[1] for r in c.exec_driver_sql(f'PRAGMA table_info({t})').fetchall()} if c.dialect.name=='sqlite' else {r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name=:t"),{'t':t}).fetchall()}
        use=[x for x in cols if x in target_cols]
        placeholders=','.join(':'+x for x in use)
        sql=f"INSERT INTO {t} ({','.join(use)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        for row in rows:
            c.execute(text(sql),{x:row[x] for x in use})
    # Reset identity sequences on PostgreSQL.
    if c.dialect.name=='postgresql':
        for t in tables:
            if 'id' in {r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name=:t"),{'t':t}).fetchall()}:
                c.execute(text(f"SELECT setval(pg_get_serial_sequence('{t}','id'),COALESCE((SELECT MAX(id) FROM {t}),1),true)"))
print('Migration completed successfully.')
