"""幂等启动升级：create_all 只建新表，不会给旧表补列。

历史部署的 kernel_policies 缺少 stratification 列；这里用方言无关的
inspector 检查后补列并回填 pooled，保证旧研究仍按原跨缸打乱口径复现。
"""
from sqlalchemy import inspect,text
from src.config.database import engine

def upgrade():
 inspector=inspect(engine)
 if 'kernel_policies' not in inspector.get_table_names():return
 columns={c['name'] for c in inspector.get_columns('kernel_policies')}
 if 'stratification' in columns:return
 with engine.begin() as conn:
  conn.execute(text("ALTER TABLE kernel_policies ADD COLUMN stratification VARCHAR NOT NULL DEFAULT 'pooled'"))
  conn.execute(text("UPDATE kernel_policies SET stratification='pooled' WHERE stratification IS NULL OR stratification=''"))
