"""按缸分层置换检验验收脚本（不依赖数据库/Redis，纯算法与服务层）。

运行：PYTHONPATH=/workspace/backend python3 -I test_acceptance.py
（-I 屏蔽 user site，这里显式挂载本机 pip --user 安装的测试依赖）
"""
import site,sys,os
site.addsitedir('/home/node/.local/lib/python3.11/site-packages')
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..','backend'))
os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ['REDIS_URL']='redis://localhost:6379/0'
import math,random
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.services.permutation import (
 permutation_test,stratified_permutation_test,EXACT_ENUMERATION_BUDGET)
from src.services.analysis import analyze
from src.services.validation import validate_vat_groups
from src.services import reports as reports_service
from src.schemas.policy import PolicyInput
from src.schemas.dataset import DatasetInput
from src.config.database import Base
from src.models import (
 ColorBatchDataset,KernelPolicy,DistributionStudy,DistributionRun,ShiftReview,Report)

failures=[]
def check(name,cond,detail=''):
 print(('PASS' if cond else 'FAIL'),name,detail)
 if not cond:failures.append(name)

def rows(points,vats):
 return [{'sample_id':'S%03d'%i,'vat_id':v,'l':p[0],'a':p[1],'b':p[2]} for i,(p,v) in enumerate(zip(points,vats))]

# ---- 参考实现：升级前 permutation_test 的逐行副本，用于证明历史口径逐位复现 ----
def legacy_permutation_test(a,b,permutations=199,seed=2407,scaling='pooled_std',bandwidth='pooled_median',sigma=None):
 import math,random,numpy as np
 from src.services.distances import samples,pairwise
 from src.services.energy import score as energy_score
 from src.services.mmd import score as mmd_score,kernel_matrix
 a,b=samples(a,b)
 pooled=np.vstack([a,b]);n,m=len(a),len(b);N=n+m;center=np.zeros(pooled.shape[1]);scales=np.ones(pooled.shape[1]);constant=[]
 if scaling=='pooled_std':
  center=np.mean(pooled,axis=0);sd=np.std(pooled,axis=0,ddof=0)
  constant=np.flatnonzero(sd==0).tolist();scales=np.where(sd==0,1.,sd);pooled=(pooled-center)/scales
 distance=pairwise(pooled);median=float(np.median(distance[np.triu_indices(N,1)]))
 if bandwidth=='pooled_median':sigma=median
 kernel=kernel_matrix(distance,sigma);ia=list(range(n));ib=list(range(n,N))
 observed_energy=energy_score(distance,ia,ib);observed_mmd=mmd_score(kernel,ia,ib)
 rng=random.Random(seed);orders=[];energy_null=[];mmd_null=[]
 for _ in range(permutations):
  order=list(range(N));rng.shuffle(order);pa=sorted(order[:n]);pb=sorted(order[n:]);orders.append(order)
  energy_null.append(energy_score(distance,pa,pb));mmd_null.append(mmd_score(kernel,pa,pb))
 def result(observed,values):
  extreme=sum(value>=observed for value in values)
  return {'statistic':observed,'extreme_count':extreme,'denominator':permutations+1,'pvalue':(1+extreme)/(permutations+1),'permutation_statistics':values}
 return {'energy':result(observed_energy,energy_null),'mmd':result(observed_mmd,mmd_null),'B':permutations,'seed':seed,'permutations':orders,'sample_sizes':[n,m]}

rng=random.Random(99);N=18
coords=[[rng.gauss(0,1),rng.gauss(0,1),rng.gauss(0,1)] for _ in range(N)]
a,b=coords[:9],coords[9:]

# 1. 历史 pooled 口径与旧实现逐位一致（两种缩放/核宽组合）
for scaling,bandwidth,sigma in [('pooled_std','pooled_median',None),('none','fixed',2.5)]:
 old=legacy_permutation_test(a,b,37,2407,scaling,bandwidth,sigma)
 new=permutation_test(a,b,37,2407,scaling,bandwidth,sigma)
 check('pooled legacy identical [%s/%s]'%(scaling,bandwidth),
  old['permutations']==new['permutations']
  and old['energy']['permutation_statistics']==new['energy']['permutation_statistics']
  and old['mmd']['permutation_statistics']==new['mmd']['permutation_statistics']
  and old['energy']['pvalue']==new['energy']['pvalue']
  and old['mmd']['pvalue']==new['mmd']['pvalue'])
check('pooled result has no stratification key','stratification' not in new)

# 2. 全枚举：2缸 × (2A+2B)，可行分组 6×6=36
vat_small=['V1','V1','V2','V2','V1','V1','V2','V2']
pts=[[rng.gauss(0,1),rng.gauss(0,1),rng.gauss(0,1)] for _ in range(8)]
ex=stratified_permutation_test(pts[:4],pts[4:],vat_small,permutations=199,seed=2407)
info=ex['stratification']
check('exact method selected',info['method']=='exact_enumeration' and info['feasible_groups']==36)
check('exact denominator 36 no +1',ex['energy']['denominator']==36 and ex['mmd']['denominator']==36
 and ex['energy']['pvalue']==ex['energy']['extreme_count']/36
 and ex['mmd']['pvalue']==ex['mmd']['extreme_count']/36)
check('exact evaluated all groups',len(ex['permutations'])==36 and info['evaluated_groups']==36)
# 每个排列保持各缸两批样本数、不跨缸移动
n=4
def vat_counts(order,vats,n_a):
 first=set(order[:n_a]);out={}
 for i,v in enumerate(vats):out.setdefault(v,[0,0]);out[v][0 if i in first else 1]+=1
 return out
valid=all(vat_counts(o,vat_small,4)=={'V1':[2,2],'V2':[2,2]} for o in ex['permutations'])
check('exact per-vat counts preserved',valid)
# 观测分配（恒等）在枚举内
obs=list(range(8))
check('observed allocation included in enumeration',obs in ex['permutations'])
check('exact p within range',0<=ex['energy']['pvalue']<=1 and 0<=ex['mmd']['pvalue']<=1)
# 枚举不重不漏
check('enumeration unique',len({tuple(o) for o in ex['permutations']})==36)

# 3. 蒙特卡洛：3缸 × (6A+6B)，可行 924^3 > 预算
vat_big=(['V1']*6+['V2']*6+['V3']*6)*2
pts=[[rng.gauss(0,1),rng.gauss(0,1),rng.gauss(0,1)] for _ in range(36)]
mc=stratified_permutation_test(pts[:18],pts[18:],vat_big,permutations=199,seed=2407)
mi=mc['stratification']
check('monte carlo selected',mi['method']=='monte_carlo' and mi['feasible_groups']==924**3 and len(mc['permutations'])==199)
check('mc +1 formula',mc['energy']['pvalue']==(1+mc['energy']['extreme_count'])/200
 and mc['mmd']['pvalue']==(1+mc['mmd']['extreme_count'])/200
 and mc['energy']['denominator']==200)
expect={'V1':[6,6],'V2':[6,6],'V3':[6,6]}
check('mc per-vat counts preserved',all(vat_counts(o,vat_big,18)==expect for o in mc['permutations']))
mc2=stratified_permutation_test(pts[:18],pts[18:],vat_big,permutations=199,seed=2407)
check('mc deterministic by seed',mc['permutations']==mc2['permutations']
 and mc['energy']['permutation_statistics']==mc2['energy']['permutation_statistics'])
mc3=stratified_permutation_test(pts[:18],pts[18:],vat_big,permutations=199,seed=2408)
check('different seed diverges',mc3['permutations']!=mc['permutations'])
check('budget boundary constant',EXACT_ENUMERATION_BUDGET==1000)

# 2b. 预算边界：每缸2A+3B → C(5,2)=10，三缸10^3=1000枚举；每缸3A+3B → C(6,3)=20，三缸20^3=8000抽样
pts_1000=[[rng.gauss(0,1),rng.gauss(0,1),rng.gauss(0,1)] for _ in range(15)]
v1000=(['E1']*2+['E2']*2+['E3']*2)+(['E1']*3+['E2']*3+['E3']*3)
r1000=stratified_permutation_test(pts_1000[:6],pts_1000[6:],v1000)
check('feasible==1000 enumerates',r1000['stratification']['feasible_groups']==1000
 and r1000['stratification']['method']=='exact_enumeration'
 and r1000['energy']['denominator']==1000 and len(r1000['permutations'])==1000)
pts_8000=[[rng.gauss(0,1),rng.gauss(0,1),rng.gauss(0,1)] for _ in range(18)]
v8000=(['E1']*3+['E2']*3+['E3']*3)*2
r8000=stratified_permutation_test(pts_8000[:9],pts_8000[9:],v8000,permutations=55,seed=11)
check('feasible==8000 monte carlo',r8000['stratification']['feasible_groups']==8000
 and r8000['stratification']['method']=='monte_carlo'
 and r8000['energy']['denominator']==56 and len(r8000['permutations'])==55)

# 4. 两检验共享同一批排列（结构上即同源；验证索引完全一致）
check('shared permutations flag',mi['shared_permutations'] is True and ex['stratification']['shared_permutations'] is True)
check('energy/mmd share order count',len(mc['energy']['permutation_statistics'])==len(mc['mmd']['permutation_statistics'])==len(mc['permutations']))

# 5. 拒绝：缺缸号 / 空缸号 / 缸内仅一批 / 只有一个缸
pts4=[[rng.gauss(0,1)]*3 for _ in range(8)]
for bad_vats,tag in [
 (['V1']*3+[None]+['V2']*4,'missing vat_id'),
 (['V1']*4+['','V2','V2','V2'],'empty vat_id'),
 (['V1']*4+['V2']*4,'single-batch vat (V1 only A)'),
 (['V1']*8,'single vat')]:
 try:
  stratified_permutation_test(pts4[:4],pts4[4:],bad_vats);ok=False
 except ValueError:ok=True
 check('reject '+tag,ok)
try:
 validate_vat_groups(
  [{'sample_id':'A1','vat_id':None,'l':0.,'a':0.,'b':0.}]*4,
  [{'sample_id':'B1','vat_id':'V2','l':0.,'a':0.,'b':0.}]*4);ok=False
except ValueError:ok=True
check('validate_vat_groups rejects missing',ok)

# 6. 零假设：每缸缸内A/B坐标完全相同（跨缸可有别）→ 缸内交换不改变统计，精确 p=1
P1=[1.,2.,.7];P2=[3.,1.,.4]
null_pts=[P1,P1,P2,P2, P1,P1,P2,P2]
null_vats=['V1','V1','V2','V2','V1','V1','V2','V2']
res0=stratified_permutation_test(null_pts[:4],null_pts[4:],null_vats)
check('within-vat null gives p=1',res0['energy']['pvalue']==1.0 and res0['mmd']['pvalue']==1.0,
 'feasible=%d'%res0['stratification']['feasible_groups'])

# 7. 关键场景：缸间构成差异混淆 vs 分层隔离
# V1: 6A+2B，V2: 2A+6B；缸间偏移大，缸内批次无差异 → pooled 误判、by_vat p=1
off1=[0.,0.,0.];off2=[8.,-6.,5.]
A=[];B=[]
for k in range(6):A.append([off1[j]+rng.gauss(0,.05) for j in range(3)])
for k in range(2):A.append([off2[j]+rng.gauss(0,.05) for j in range(3)])
for k in range(2):B.append([off1[j]+rng.gauss(0,.05) for j in range(3)])
for k in range(6):B.append([off2[j]+rng.gauss(0,.05) for j in range(3)])
# 合并顺序为 [A(8), B(8)]：V1=6A+2B，V2=2A+6B
vats=(['V1']*6+['V2']*2)+(['V1']*2+['V2']*6)
pooled_conf=permutation_test(A,B,199,2407,'none','fixed',3.)
strat=stratified_permutation_test(A,B,vats,199,2407,'none','fixed',3.)
check('pooled is more extreme than stratified under vat confound',
 pooled_conf['energy']['pvalue']<strat['energy']['pvalue']
 and pooled_conf['mmd']['pvalue']<=strat['mmd']['pvalue'],
 'pooled p=%s stratified p=%s'%(pooled_conf['energy']['pvalue'],strat['energy']['pvalue']))
# 缸内不变构造：每缸8个点坐标完全相同（缸间偏移大），任何缸内交换都不改变统计 → 分层p=1
cA=[];cB=[];cvA=[];cvB=[]
for v,off in [('V1',[0.,0.,0.]),('V2',[7.,-5.,4.])]:
 cA.extend([off[:] for _ in range(3)]);cB.extend([off[:] for _ in range(3)]);cvA.extend([v]*3);cvB.extend([v]*3)
cv=cvA+cvB
strat_eq=stratified_permutation_test(cA,cB,cv,199,2407,'none','fixed',3.)
check('stratified exact p=1 when within-vat points are identical',strat_eq['energy']['pvalue']==1.0
 and strat_eq['mmd']['pvalue']==1.0 and strat_eq['stratification']['method']=='exact_enumeration',
 'feasible=%d'%strat_eq['stratification']['feasible_groups'])

# 8. 缸内强批次效应 → MC 最小 p
seA=[];seB=[];seV=[]
for v,off in [('V1',[0.,0.,0.]),('V2',[4.,4.,4.]),('V3',[-3.,2.,1.])]:
 for k in range(4):
  seA.append([off[j]+rng.gauss(0,.03) for j in range(3)])
  seB.append([off[j]+5.+rng.gauss(0,.03) for j in range(3)])
# 合并顺序 [A12, B12]：每缸各4条A、4条B
seV=['V1']*4+['V2']*4+['V3']*4+['V1']*4+['V2']*4+['V3']*4
strong=stratified_permutation_test(seA,seB,seV,99,2407,'none','fixed',2.)
check('strong within-vat effect hits minimum p',
 strong['energy']['extreme_count']==0 and strong['energy']['pvalue']==1/100
 and strong['mmd']['extreme_count']==0 and strong['mmd']['pvalue']==1/100)

# 9. analyze 调度：旧快照无 stratification → pooled；新快照 by_vat 带分层依据
snap_pooled={'dataset':{'batch_a':[{'sample_id':'A%d'%i,'l':p[0],'a':p[1],'b':p[2]} for i,p in enumerate(A)],
                        'batch_b':[{'sample_id':'B%d'%i,'l':p[0],'a':p[1],'b':p[2]} for i,p in enumerate(B)]},
             'policy':{'permutations':49,'seed':7,'scaling':'none','bandwidth':'fixed','sigma':3.}}
out_pooled=analyze(snap_pooled)
check('legacy snapshot reproduces pooled','stratification' not in out_pooled and len(out_pooled['assumptions'])==5)
snap_vat={'dataset':{'batch_a':rows(A,vats[:8]),'batch_b':rows(B,vats[8:])},
          'policy':{'permutations':49,'seed':7,'scaling':'none','bandwidth':'fixed','sigma':3.,'stratification':'by_vat'}}
out_vat=analyze(snap_vat)
check('analyze dispatches stratified',out_vat['stratification']['mode']=='by_vat'
 and 'feasible_groups' in out_vat['stratification'] and out_vat['stratification']['sampling_basis'])
check('frozen sampling basis traceable',('预算' in out_vat['stratification']['sampling_basis']))
check('stratified assumptions appended',len(out_vat['assumptions'])>5
 and any('缸内交换' in s for s in out_vat['assumptions']))
check('checksum still over snapshot',len(out_vat['checksum'])==64)

# 10. Pydantic 口径/数据 schema
p=PolicyInput(name='分层口径x',scaling='none',bandwidth='fixed',sigma=1.,permutations=99,seed=1,stratification='by_vat')
check('policy schema by_vat',p.stratification=='by_vat')
p_default=PolicyInput(name='默认口径x',scaling='none',bandwidth='fixed',sigma=1.,permutations=99,seed=1)
check('policy schema defaults pooled',p_default.stratification=='pooled')
d=DatasetInput(name='数据集x',source='src.json',
 batch_a=[{'sample_id':'A1','vat_id':'V1','l':1.,'a':1.,'b':1.}]*4,
 batch_b=[{'sample_id':'B%d'%i,'vat_id':'V1','l':1.,'a':1.,'b':1.} for i in range(4)])
check('dataset schema vat_id optional',d.batch_a[0].vat_id=='V1')
d2=DatasetInput(name='数据集y',source='src.json',
 batch_a=[{'sample_id':'A%d'%i,'l':1.,'a':1.,'b':1.} for i in range(4)],
 batch_b=[{'sample_id':'B%d'%i,'l':1.,'a':1.,'b':1.} for i in range(4)])
check('dataset schema allows no vat_id',all(r.vat_id is None for r in d2.batch_a))

# 11. SQLite 内存库：研究冻结拒绝 + CSV 分层列（验证服务层与历史兼容导出）
engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
LS=sessionmaker(bind=engine);db=LS()
ds_bad=ColorBatchDataset(id='d-bad',name='缺缸号数据',source='x.json',
 batch_a=[{'sample_id':'A%d'%i,'l':1.,'a':1.,'b':1.} for i in range(4)],
 batch_b=[{'sample_id':'B%d'%i,'l':1.,'a':1.,'b':1.} for i in range(4)],created_at='t')
pol_vat=KernelPolicy(id='p-vat',name='分层口径',scaling='none',bandwidth='fixed',sigma=3.,
 permutations=49,seed=7,stratification='by_vat',created_at='t')
pol_pool=KernelPolicy(id='p-pool',name='历史口径',scaling='none',bandwidth='fixed',sigma=3.,
 permutations=49,seed=7,stratification='pooled',created_at='t')
db.add_all([ds_bad,pol_vat,pol_pool]);db.commit()
from src.schemas.study import StudyInput
from src.services import studies as studies_service
try:
 studies_service.create(db,StudyInput(name='应被拒绝的研究',dataset_id='d-bad',policy_id='p-vat'));rejected=False
except Exception as e:
 rejected=e.status_code==422 and '缸号' in str(e)
check('study freeze rejects missing vat (422)',rejected)
# 单批缸同样拒绝
ds_one=ColorBatchDataset(id='d-one',name='单批缸数据',source='x.json',
 batch_a=[{'sample_id':'A%d'%i,'vat_id':'V1','l':1.,'a':1.,'b':1.} for i in range(4)],
 batch_b=[{'sample_id':'B%d'%i,'vat_id':'V2','l':1.,'a':1.,'b':1.} for i in range(4)],created_at='t')
db.add(ds_one);db.commit()
try:
 studies_service.create(db,StudyInput(name='单批缸研究',dataset_id='d-one',policy_id='p-vat'));rejected=False
except Exception as e:
 rejected=e.status_code==422 and '只有一批' in str(e)
check('study freeze rejects single-batch vat (422)',rejected)
# 正常分层研究→运行→复核→报告→CSV
ds_ok=ColorBatchDataset(id='d-ok',name='三缸数据',source='x.json',
 batch_a=rows(seA,seV[:12]),batch_b=[{**r,'sample_id':'B%02d'%i} for i,r in enumerate(rows(seB,seV[12:]))],created_at='t')
db.add(ds_ok);db.commit()
study=studies_service.create(db,StudyInput(name='分层研究ok',dataset_id='d-ok',policy_id='p-vat'))
run=DistributionRun(id='r-1',study_id=study['id'],status='completed',result=analyze(study['snapshot']),error='',created_at='t')
rev=ShiftReview(id='v-1',run_id='r-1',version=1,note='分层复核依据足够长的备注文字。',decision='accepted',author='analyst@x',created_at='t')
rep=Report(id='rep-1',run_id='r-1',review_id='v-1',title='分层归档',published_by='admin@x',created_at='t')
db.add_all([run,rev,rep]);db.commit()
csv_text=reports_service.export(db,'rep-1')
header=csv_text.splitlines()[0].lstrip('﻿').split(',')
for col in ('stratification','permutation_method','feasible_groups','sampling_basis'):
 check('CSV header has %s'%col,col in header)
line1=csv_text.splitlines()[1]
check('CSV row marks by_vat',',by_vat,monte_carlo,' in line1 and '缸内交换' in line1)
# 历史 pooled 运行导出：新列存在且填 pooled 默认
study2=studies_service.create(db,StudyInput(name='历史研究ok',dataset_id='d-ok',policy_id='p-pool'))
# pooled 口径不需要缸号也允许；用无缸号数据另建
ds_legacy=ColorBatchDataset(id='d-leg',name='无缸号历史数据',source='x.json',
 batch_a=[{'sample_id':'LA%d'%i,'l':1.,'a':1.,'b':1.} for i in range(4)],
 batch_b=[{'sample_id':'LB%d'%i,'l':1.,'a':1.,'b':1.} for i in range(4)],created_at='t')
db.add(ds_legacy);db.commit()
study3=studies_service.create(db,StudyInput(name='历史pooled研究',dataset_id='d-leg',policy_id='p-pool'))
run3=DistributionRun(id='r-3',study_id=study3['id'],status='completed',result=analyze(study3['snapshot']),error='',created_at='t')
rev3=ShiftReview(id='v-3',run_id='r-3',version=1,note='历史口径复核备注足够长。',decision='accepted',author='analyst@x',created_at='t')
rep3=Report(id='rep-3',run_id='r-3',review_id='v-3',title='历史归档',published_by='admin@x',created_at='t')
db.add_all([run3,rev3,rep3]);db.commit()
csv3=reports_service.export(db,'rep-3')
check('legacy CSV marks pooled',',pooled,monte_carlo,' in csv3 and '跨缸打乱历史口径' in csv3)
check('legacy run has no stratification block','stratification' not in run3.result)

print()
if failures:print('FAILURES:',failures);sys.exit(1)
print('ALL CHECKS PASSED')
