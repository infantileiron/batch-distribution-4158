import random,json
from sqlalchemy import select,func
from src.config.database import Base,engine,Session
from src.models import User,ColorBatchDataset,KernelPolicy,DistributionStudy,DistributionRun,ShiftReview,Report
from src.services.analysis import analyze
from src.utils.security import hash_password
from src.utils.time import now
from src.utils.serialization import serialize

def seed():
 from src.config.migration import upgrade as upgrade_schema
 upgrade_schema()
 Base.metadata.create_all(engine)
 with Session() as db:
  for role in ('admin','analyst','viewer'):
   if not db.get(User,role):db.add(User(id=role,email=role+'@qichuan.demo',password=hash_password('Color2026!'),role=role))
  rng=random.Random(2407);a=[];b=[];center=[68.,12.,18.]
  for i in range(45):
   va=[rng.gauss(0,s) for s in (1.0,.65,.8)];vb=[2.8+rng.gauss(0,.6),2.2+rng.gauss(0,.45),rng.gauss(0,1.6)]
   for sign in (-1,1):
    a.append({'sample_id':f'A{len(a)+1:03}',**{key:round(c+sign*v,6) for key,c,v in zip(('l','a','b'),center,va)}});b.append({'sample_id':f'B{len(b)+1:03}',**{key:round(c+sign*v,6) for key,c,v in zip(('l','a','b'),center,vb)}})
  if not db.get(ColorBatchDataset,'demo-data'):db.add(ColorBatchDataset(id='demo-data',name='绮川·同均值异分布两批色样',source='qichuan_lab_batches_20261112.json',batch_a=a,batch_b=b,created_at=now()));db.flush()
  # 按缸分层演示：3个缸，缸间均值差异明显，仅缸内交换批次归属才有意义
  vrng=random.Random(7311);vat_a=[];vat_b=[];vat_offsets={'VAT-01':(0.,0.,0.),'VAT-02':(3.2,-1.4,1.1),'VAT-03':(-2.6,1.8,-0.9)}
  for vat,offset in vat_offsets.items():
   for k in range(6):
    jitter=[vrng.gauss(0,s) for s in (.55,.4,.5)]
    vat_a.append({'sample_id':f'{vat}-A{k+1}','vat_id':vat,**{key:round(c+off+j,6) for key,c,off,j in zip(('l','a','b'),center,offset,jitter)}})
    vat_b.append({'sample_id':f'{vat}-B{k+1}','vat_id':vat,**{key:round(c+off+j+delta,6) for key,c,off,j,delta in zip(('l','a','b'),center,offset,jitter,(.45,.35,.25))}})
  if not db.get(ColorBatchDataset,'demo-vat-data'):db.add(ColorBatchDataset(id='demo-vat-data',name='绮川·三缸分层两批色样（缸间有差）',source='qichuan_vat_batches_20261112.json',batch_a=vat_a,batch_b=vat_b,created_at=now()));db.flush()
  for id,name,scaling,width,sigma in [('demo-policy','合并总体SD·合并中位核宽','pooled_std','pooled_median',None),('demo-fixed','原始色度·固定sigma3','none','fixed',3.)]:
   if not db.get(KernelPolicy,id):db.add(KernelPolicy(id=id,name=name,scaling=scaling,bandwidth=width,sigma=sigma,permutations=199,seed=2407,stratification='pooled',created_at=now()))
  if not db.get(KernelPolicy,'demo-vat-policy'):db.add(KernelPolicy(id='demo-vat-policy',name='按缸分层·缸内交换归属',scaling='pooled_std',bandwidth='pooled_median',sigma=None,permutations=199,seed=2407,stratification='by_vat',created_at=now()))
  db.flush()
  if not db.get(DistributionStudy,'demo-study'):db.add(DistributionStudy(id='demo-study',name='同均值色样·方差与多峰复核',dataset_id='demo-data',policy_id='demo-policy',snapshot={'dataset':serialize(db.get(ColorBatchDataset,'demo-data')),'policy':serialize(db.get(KernelPolicy,'demo-policy'))},created_at=now()));db.flush()
  if not db.get(DistributionStudy,'demo-vat-study'):db.add(DistributionStudy(id='demo-vat-study',name='三缸色样·按缸分层迁移复核',dataset_id='demo-vat-data',policy_id='demo-vat-policy',snapshot={'dataset':serialize(db.get(ColorBatchDataset,'demo-vat-data')),'policy':serialize(db.get(KernelPolicy,'demo-vat-policy'))},created_at=now()));db.flush()
  if not db.get(DistributionRun,'demo-run'):db.add(DistributionRun(id='demo-run',study_id='demo-study',status='completed',result=analyze(db.get(DistributionStudy,'demo-study').snapshot),error='',created_at=now()));db.flush()
  if not db.get(DistributionRun,'demo-vat-run'):db.add(DistributionRun(id='demo-vat-run',study_id='demo-vat-study',status='completed',result=analyze(db.get(DistributionStudy,'demo-vat-study').snapshot),error='',created_at=now()));db.flush()
  if not db.get(ShiftReview,'demo-review'):db.add(ShiftReview(id='demo-review',run_id='demo-run',version=1,note='两批原始均值相同而方差和多峰不同；Energy与MMD分别复核，p未多重校正且不是迁移概率。独立可交换假设不覆盖同缸相关样本。',decision='accepted',author='analyst@qichuan.demo',created_at=now()));db.flush()
  if not db.get(ShiftReview,'demo-vat-review'):db.add(ShiftReview(id='demo-vat-review',run_id='demo-vat-run',version=1,note='按缸分层后缸间差异不再进入零分布，仅保留缸内批次归属交换；两检验共享缸内排列，p未多重校正且不是迁移概率。',decision='accepted',author='analyst@qichuan.demo',created_at=now()));db.flush()
  if not db.get(Report,'demo-report'):db.add(Report(id='demo-report',run_id='demo-run',review_id='demo-review',title='绮川色样·分布迁移人工复核',published_by='admin@qichuan.demo',created_at=now()))
  if not db.get(Report,'demo-vat-report'):db.add(Report(id='demo-vat-report',run_id='demo-vat-run',review_id='demo-vat-review',title='绮川三缸色样·分层迁移人工复核',published_by='admin@qichuan.demo',created_at=now()))
  db.commit();return {m.__tablename__:db.scalar(select(func.count()).select_from(m)) for m in (User,ColorBatchDataset,KernelPolicy,DistributionStudy,DistributionRun,ShiftReview,Report)}
if __name__=='__main__':print(json.dumps(seed(),ensure_ascii=False))
