"""模拟历史部署升级：旧表无 stratification 列 → 启动迁移补列回填 pooled → 旧研究仍按 pooled 复现。"""
import site,sys,os
site.addsitedir('/home/node/.local/lib/python3.11/site-packages')
sys.path.insert(0,'/workspace/backend')
os.environ['DATABASE_URL']='sqlite:////tmp/legacy_upgrade.db'
os.environ['REDIS_URL']='redis://localhost:6379/0'
from sqlalchemy import create_engine,inspect,text
from src.config.migration import upgrade

DB='/tmp/legacy_upgrade.db'
if os.path.exists(DB):os.remove(DB)
engine=create_engine('sqlite:///'+DB)
# 1. 按历史 schema 手工建旧表（无 stratification）并插入旧口径
with engine.begin() as c:
 c.execute(text("""CREATE TABLE kernel_policies (
  id VARCHAR PRIMARY KEY, name VARCHAR UNIQUE, scaling VARCHAR, bandwidth VARCHAR,
  sigma DOUBLE, permutations INTEGER, seed INTEGER, created_at VARCHAR)"""))
 c.execute(text("INSERT INTO kernel_policies (id,name,scaling,bandwidth,sigma,permutations,seed,created_at) VALUES ('old','旧口径','none','fixed',3,49,7,'t')"))
insp=inspect(engine)
assert 'stratification' not in {x['name'] for x in insp.get_columns('kernel_policies')}
# 2. 跑启动迁移（main/worker/seed 启动时都会调用）
upgrade()
insp=inspect(engine)
assert 'stratification' in {x['name'] for x in insp.get_columns('kernel_policies')},'迁移未补列'
with engine.connect() as c:
 row=c.execute(text("SELECT id,stratification FROM kernel_policies")).fetchone()
 print('backfilled row:',row);assert row==('old','pooled')
# 3. 幂等：再次升级不报错不重复补列
upgrade();upgrade()
print('legacy upgrade + backfill + idempotency: ok')
