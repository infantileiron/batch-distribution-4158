import math,random
from itertools import combinations
from collections import OrderedDict
import numpy as np
from src.services.distances import samples,pairwise
from src.services.energy import score as energy_score
from src.services.mmd import score as mmd_score,kernel_matrix

# 可行分组（保持各缸两批样本数的缸内归属分配总数）不超过该预算时全枚举给精确p，
# 否则退回固定seed的蒙特卡洛抽样，沿用 (1+extreme)/(B+1) 加一口径。
EXACT_ENUMERATION_BUDGET=1000

def _prepare(a,b,scaling,bandwidth,sigma):
 a,b=samples(a,b)
 pooled=np.vstack([a,b]);n,m=len(a),len(b);N=n+m;center=np.zeros(pooled.shape[1]);scales=np.ones(pooled.shape[1]);constant=[]
 if scaling=='pooled_std':
  center=np.mean(pooled,axis=0);sd=np.std(pooled,axis=0,ddof=0)
  if not np.isfinite(center).all() or not np.isfinite(sd).all():raise ValueError('pooled scaling overflow')
  constant=np.flatnonzero(sd==0).tolist();scales=np.where(sd==0,1.,sd);pooled=(pooled-center)/scales
 elif scaling!='none':raise ValueError('unknown scaling')
 distance=pairwise(pooled);median=float(np.median(distance[np.triu_indices(N,1)]))
 if bandwidth=='pooled_median':
  if median<=0 or not math.isfinite(median):raise ValueError('pooled median为0，自动核宽不可估；请选择明确正值的固定sigma，不跳过零距离')
  sigma=median
 elif bandwidth=='fixed':
  if sigma is None or not math.isfinite(sigma) or sigma<=0:raise ValueError('fixed sigma must be positive')
 else:raise ValueError('unknown bandwidth policy')
 kernel=kernel_matrix(distance,sigma)
 transform={'scaling':scaling,'center':center.tolist(),'scales':scales.tolist(),'constant_dimensions':constant,'constant_dimension_policy':'pooled SD=0 dimensions centered to 0 with scale=1; explicitly retained','bandwidth':bandwidth,'sigma':float(sigma),'pooled_median_distance':median,'label_independent':True}
 return pooled,n,m,N,distance,kernel,transform

def _check_permutation_args(permutations,seed):
 if isinstance(permutations,bool) or not isinstance(permutations,int) or not 1<=permutations<=1999:raise ValueError('invalid permutation count')
 if isinstance(seed,bool) or not isinstance(seed,int) or seed<0:raise ValueError('invalid seed')

def permutation_test(a,b,permutations=199,seed=2407,scaling='pooled_std',bandwidth='pooled_median',sigma=None):
 _check_permutation_args(permutations,seed)
 pooled,n,m,N,distance,kernel,transform=_prepare(a,b,scaling,bandwidth,sigma)
 ia=list(range(n));ib=list(range(n,N));observed_energy=energy_score(distance,ia,ib);observed_mmd=mmd_score(kernel,ia,ib)
 rng=random.Random(seed);orders=[];energy_null=[];mmd_null=[]
 for _ in range(permutations):
  order=list(range(N));rng.shuffle(order);pa=sorted(order[:n]);pb=sorted(order[n:]);orders.append(order);energy_null.append(energy_score(distance,pa,pb));mmd_null.append(mmd_score(kernel,pa,pb))
 def result(observed,values):
  extreme=sum(value>=observed for value in values)
  return {'statistic':observed,'extreme_count':extreme,'denominator':permutations+1,'pvalue':(1+extreme)/(permutations+1),'permutation_statistics':values}
 return {'energy':result(observed_energy,energy_null),'mmd':result(observed_mmd,mmd_null),'B':permutations,'seed':seed,'permutations':orders,'sample_sizes':[n,m],'transform':transform,'transformed_a':pooled[:n].tolist(),'transformed_b':pooled[n:].tolist(),'comparison':'>= observed; strict Float64 evaluation; +1 numerator and denominator','pvalues_adjusted':False}

def _vat_layout(vat_ids,n):
 """按缸号归集合并索引（前n为A批，其余为B批），强制缺缸号/单批缸拒绝。"""
 vats=OrderedDict()
 for idx,vat in enumerate(vat_ids):
  if vat is None or not str(vat).strip():raise ValueError('按缸分层检验要求每条读数提供缸号vat_id；存在缺缸号样本，拒绝运行')
  vats.setdefault(str(vat).strip(),[]).append(idx)
 layout=[]
 for vat,indices in vats.items():
  a_idx=sorted(i for i in indices if i<n);b_idx=sorted(i for i in indices if i>=n)
  if not a_idx or not b_idx:raise ValueError('缸内只有一批样本，无法缸内交换归属，拒绝运行；问题缸号：%s'%vat)
  layout.append({'vat_id':vat,'indices':sorted(indices),'n_a':len(a_idx),'n_b':len(b_idx)})
 if len(layout)<2:raise ValueError('按缸分层检验至少需要两个缸以分离缸间差异；当前缸数：%d'%len(layout))
 return layout

def stratified_permutation_test(a,b,vat_ids,permutations=199,seed=2407,scaling='pooled_std',bandwidth='pooled_median',sigma=None,exact_budget=EXACT_ENUMERATION_BUDGET):
 _check_permutation_args(permutations,seed)
 pooled,n,m,N,distance,kernel,transform=_prepare(a,b,scaling,bandwidth,sigma)
 layout=_vat_layout(vat_ids,n)
 observed_a=list(range(n));observed_b=list(range(n,N))
 observed_energy=energy_score(distance,observed_a,observed_b);observed_mmd=mmd_score(kernel,observed_a,observed_b)
 # 各缸可行分配数 C(n_v_total,n_v_a) 与总体可行分组数（保持各缸两批样本数）
 feasible=1;vat_info=[]
 for layer in layout:
  total=layer['n_a']+layer['n_b'];ways=math.comb(total,layer['n_a']);feasible*=ways
  vat_info.append({'vat_id':layer['vat_id'],'n_total':total,'n_a':layer['n_a'],'n_b':layer['n_b'],'feasible_groups':ways})
 def order_from(pa,pb):return sorted(pa)+sorted(pb)
 if feasible<=exact_budget:
  # 全枚举：逐缸组合后笛卡尔积；观测分配本身是其中一组，必然纳入，无需+1校正
  per_vat=[list(combinations(layer['indices'],layer['n_a'])) for layer in layout]
  orders=[];energy_null=[];mmd_null=[]
  def recurse(depth,chosen):
   if depth==len(layout):
    pa=sorted(i for group in chosen for i in group);pb=sorted(set(range(N))-set(pa))
    orders.append(order_from(pa,pb));energy_null.append(energy_score(distance,pa,pb));mmd_null.append(mmd_score(kernel,pa,pb));return
   for group in per_vat[depth]:recurse(depth+1,chosen+[group])
  recurse(0,[])
  evaluated=len(orders)
  def result(observed,values):
   extreme=sum(value>=observed for value in values)
   return {'statistic':observed,'extreme_count':extreme,'denominator':evaluated,'pvalue':extreme/evaluated,'permutation_statistics':values}
  method='exact_enumeration';comparison='>= observed; exhaustive within-vat allocations preserving per-vat batch counts; exact p = extreme_count/denominator with observed allocation included; no +1 correction'
  sampling_basis='可行分组%d未超预算%d，全枚举全部缸内归属分配，观测分配计入分母，精确p不加+1。'%(feasible,exact_budget)
  B=evaluated
 else:
  # 蒙特卡洛：固定seed逐缸shuffle，仅缸内交换批次归属；两检验共享同一批分配，沿用+1口径
  rng=random.Random(seed);orders=[];energy_null=[];mmd_null=[]
  for _ in range(permutations):
   pa=[]
   for layer in layout:
    order=list(layer['indices']);rng.shuffle(order);pa.extend(sorted(order[:layer['n_a']]))
   pa=sorted(pa);pb=sorted(set(range(N))-set(pa))
   orders.append(order_from(pa,pb));energy_null.append(energy_score(distance,pa,pb));mmd_null.append(mmd_score(kernel,pa,pb))
  evaluated=permutations
  def result(observed,values):
   extreme=sum(value>=observed for value in values)
   return {'statistic':observed,'extreme_count':extreme,'denominator':permutations+1,'pvalue':(1+extreme)/(permutations+1),'permutation_statistics':values}
  method='monte_carlo';comparison='>= observed; within-vat shuffled allocations preserving per-vat batch counts; strict Float64 evaluation; +1 numerator and denominator'
  sampling_basis='可行分组%d超过预算%d，按seed=%d随机抽取%d次缸内交换分配，保留各缸两批样本数；p=(1+极端次数)/(B+1)，+1口径与历史pooled随机排列一致。'%(feasible,exact_budget,seed,permutations)
  B=permutations
 stratification={'mode':'by_vat','exact_budget':exact_budget,'feasible_groups':feasible,'method':method,'evaluated_groups':evaluated,'observed_allocation_included':method=='exact_enumeration','vat_order':[v['vat_id'] for v in vat_info],'vats':vat_info,'sampling_basis':sampling_basis,'shared_permutations':True,'per_vat_batch_counts_preserved':True}
 return {'energy':result(observed_energy,energy_null),'mmd':result(observed_mmd,mmd_null),'B':B,'seed':seed,'permutations':orders,'sample_sizes':[n,m],'transform':transform,'transformed_a':pooled[:n].tolist(),'transformed_b':pooled[n:].tolist(),'comparison':comparison,'pvalues_adjusted':False,'stratification':stratification}
