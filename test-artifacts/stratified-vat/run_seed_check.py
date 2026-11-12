import site,sys,os
site.addsitedir('/home/node/.local/lib/python3.11/site-packages')
sys.path.insert(0,'/workspace/backend')
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/seed_demo.db')
os.environ.setdefault('REDIS_URL','redis://localhost:6379/0')
import sqlite3;print('sqlite',sqlite3.sqlite_version)
from scripts.seed_demo import seed
print('first seed:',seed())
from src.config.database import Session
from src.models import DistributionRun,KernelPolicy,ColorBatchDataset
with Session() as db:
 r=db.get(DistributionRun,'demo-vat-run');info=r.result['stratification']
 print('vat run method:',info['method'],'feasible:',info['feasible_groups'],'B:',r.result['B'])
 print('vat p energy/mmd:',r.result['energy']['pvalue'],r.result['mmd']['pvalue'])
 print('vat per-vat:',[(v['vat_id'],v['n_a'],v['n_b'],v['feasible_groups']) for v in info['vats']])
 print('legacy run pooled:', 'stratification' not in db.get(DistributionRun,'demo-run').result)
 print('policies:',[(p.id,p.stratification) for p in db.query(KernelPolicy).all()])
 print('vat dataset vat_ids sample:',[d['vat_id'] for d in db.get(ColorBatchDataset,'demo-vat-data').batch_a[:4]])
print('second seed (idempotent):',seed())
# 迁移幂等性：重复执行 upgrade 不应报错
from src.config.migration import upgrade
upgrade();upgrade()
print('migration upgrade idempotent: ok')
