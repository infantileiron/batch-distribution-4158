"""HTTP 端到端：JWT 写权限 → 数据/口径导入 → 分层拒绝(422) → 合法研究 → 运行结果 → 归档 CSV 分层列。"""
import site,sys,os
site.addsitedir('/home/node/.local/lib/python3.11/site-packages')
sys.path.insert(0,'/workspace/backend')
os.environ['DATABASE_URL']='sqlite:////tmp/e2e.db'
os.environ['REDIS_URL']='redis://localhost:6379/0'
DB='/tmp/e2e.db'
if os.path.exists(DB):os.remove(DB)
from fastapi.testclient import TestClient
from src.main import app
import jwt
from src.config.settings import JWT_SECRET
from src.config.database import Session
from src.models import DistributionRun,DistributionStudy,ShiftReview,Report
from src.services.analysis import analyze
from src.utils.time import now
import uuid

def tok(role,email):return jwt.encode({'sub':email,'role':role,'email':email},JWT_SECRET,algorithm='HS256')
analyst=tok('analyst','analyst@qichuan.demo')
admin=tok('admin','admin@qichuan.demo')
H={'Authorization':'Bearer '+analyst};HA={'Authorization':'Bearer '+admin}
fails=[]
def check(n,c,d=''):
 print('PASS' if c else 'FAIL',n,d);
 if not c:fails.append(n)

with TestClient(app) as client:
 # 1. 无缸号数据集（历史形态仍可导入）
 no_vat={'name':'无缸号对照','source':'s.json',
  'batch_a':[{'sample_id':'A%d'%i,'l':1.,'a':1.,'b':1.} for i in range(4)],
  'batch_b':[{'sample_id':'B%d'%i,'l':1.,'a':1.,'b':1.} for i in range(4)]}
 r=client.post('/datasets',json=no_vat,headers=H);check('legacy dataset import 200',r.status_code==200,r.status_code)
 ds_no=r.json()['id']
 # 2. by_vat 口径
 r=client.post('/policies',json={'name':'分层口径','scaling':'none','bandwidth':'fixed','sigma':3.,
  'permutations':49,'seed':7,'stratification':'by_vat'},headers=H)
 check('by_vat policy 200',r.status_code==200,r.text);pol_vat=r.json()['id']
 # 3. pooled 口径（省略 stratification → 默认 pooled）
 r=client.post('/policies',json={'name':'历史口径','scaling':'none','bandwidth':'fixed','sigma':3.,
  'permutations':49,'seed':7},headers=H)
 check('pooled policy default 200',r.status_code==200 and r.json()['stratification']=='pooled',r.text);pol_pool=r.json()['id']
 # 4. 无缸号数据 + by_vat 口径 → 研究冻结 422
 r=client.post('/studies',json={'name':'应拒绝','dataset_id':ds_no,'policy_id':pol_vat},headers=H)
 check('freeze rejects missing vat 422',r.status_code==422 and '缸号' in r.json()['detail'],(r.status_code,r.text))
 # 5. 单批缸数据 → 422
 one_vat={'name':'单批缸','source':'s.json',
  'batch_a':[{'sample_id':'A%d'%i,'vat_id':'V1','l':1.,'a':1.,'b':1.} for i in range(4)],
  'batch_b':[{'sample_id':'B%d'%i,'vat_id':'V2','l':1.,'a':1.,'b':1.} for i in range(4)]}
 r=client.post('/datasets',json=one_vat,headers=H);ds_one=r.json()['id']
 r=client.post('/studies',json={'name':'单批缸研究','dataset_id':ds_one,'policy_id':pol_vat},headers=H)
 check('freeze rejects single-batch vat 422',r.status_code==422 and '只有一批' in r.json()['detail'],(r.status_code,r.text))
 # 6. 合法三缸数据 → 研究 200
 vat_ds={'name':'三缸对照','source':'s.json','batch_a':[],'batch_b':[]}
 for v in ('V1','V2','V3'):
  for k in range(4):
   vat_ds['batch_a'].append({'sample_id':'%s-A%d'%(v,k),'vat_id':v,'l':1.+k*.1,'a':.5,'b':.7})
   vat_ds['batch_b'].append({'sample_id':'%s-B%d'%(v,k),'vat_id':v,'l':1.4+k*.1,'a':.9,'b':1.1})
 r=client.post('/datasets',json=vat_ds,headers=H);check('vat dataset 200',r.status_code==200,r.text);ds=r.json()['id']
 r=client.post('/studies',json={'name':'分层研究','dataset_id':ds,'policy_id':pol_vat},headers=H)
 check('stratified study 200',r.status_code==200,r.text);study=r.json()
 # 7. 直接计算运行结果（绕过 redis 队列），落库为 completed
 result=analyze(study['snapshot'])
 with Session() as db:
  run=DistributionRun(id=str(uuid.uuid4()),study_id=study['id'],status='completed',result=result,error='',created_at=now())
  db.add(run);db.commit();rid=run.id
 # 8. 复核接受 + 管理员归档 + 下载 CSV
 r=client.post('/reviews',json={'run_id':rid,'note':'分层检验复核依据足够长的备注内容。','decision':'accepted'},headers=H)
 check('review 200',r.status_code==200,r.text)
 r=client.post('/reports',json={'run_id':rid,'title':'分层归档'},headers=HA)
 check('report 200',r.status_code==200,r.text);rep=r.json()['id']
 r=client.get('/reports/%s/csv'%rep,headers=H)
 check('csv 200',r.status_code==200,r.status_code)
 txt=r.text
 check('csv stratified columns',all(c in txt for c in ('stratification','permutation_method','feasible_groups','sampling_basis','by_vat')),txt[:120])
 check('csv exact or mc consistent',('exact_enumeration' in txt) or ('monte_carlo' in txt))
 # 9. 无缸号数据 + pooled 历史口径仍可冻结、可分析
 r=client.post('/studies',json={'name':'历史研究','dataset_id':ds_no,'policy_id':pol_pool},headers=H)
 check('legacy pooled study 200',r.status_code==200,r.text);legacy_study=r.json()
 legacy_result=analyze(legacy_study['snapshot'])
 check('legacy result pooled no block','stratification' not in legacy_result and legacy_result['energy']['denominator']==50)
 # 10. viewer 禁止写入
 viewer=tok('viewer','v@x')
 r=client.post('/policies',json={'name':'x','scaling':'none','bandwidth':'fixed','sigma':1.,'permutations':49,'seed':1},
  headers={'Authorization':'Bearer '+viewer})
 check('viewer forbidden 403',r.status_code==403,r.status_code)

print()
if fails:print('FAILURES',fails);sys.exit(1)
print('E2E ALL PASSED')
