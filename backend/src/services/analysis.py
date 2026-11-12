import hashlib,json,statistics
from src.services.permutation import permutation_test,stratified_permutation_test
from src.services.validation import validate_vat_groups

def analyze(snapshot):
 data=snapshot['dataset'];policy=snapshot['policy'];a=[[r[k] for k in ('l','a','b')] for r in data['batch_a']];b=[[r[k] for k in ('l','a','b')] for r in data['batch_b']]
 # 历史研究快照无stratification字段时按pooled原口径复现；by_vat强制缸号与缸内两批校验
 mode=policy.get('stratification','pooled')
 if mode=='by_vat':
  validate_vat_groups(data['batch_a'],data['batch_b'])
  vat_ids=[r['vat_id'] for r in data['batch_a']]+[r['vat_id'] for r in data['batch_b']]
  result=stratified_permutation_test(a,b,vat_ids,policy['permutations'],policy['seed'],policy['scaling'],policy['bandwidth'],policy['sigma'])
 elif mode=='pooled':
  result=permutation_test(a,b,policy['permutations'],policy['seed'],policy['scaling'],policy['bandwidth'],policy['sigma'])
 else:raise ValueError('unknown stratification: %s'%mode)
 summaries=[]
 for label,rows in (('A',a),('B',b)):
  summaries.append({'batch':label,'n':len(rows),'mean':[statistics.fmean(x[j] for x in rows) for j in range(3)],'population_sd':[statistics.pstdev(x[j] for x in rows) for j in range(3)]})
 assumptions=list(_base_assumptions())
 if mode=='by_vat':assumptions=assumptions+list(_stratified_assumptions(result))
 return {**result,'raw_a':data['batch_a'],'raw_b':data['batch_b'],'summaries':summaries,'policy':policy,'checksum':hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'assumptions':assumptions}

def _base_assumptions():
 yield 'Energy V使用欧氏距离，组内均值包含对角；MMD U使用RBF核，组内排对角并按n(n-1)归一，原始U值可为负，不截0。'
 yield '缩放仅在合并样本上估计总体均值/SD；自动sigma为合并样本全部非对角欧氏距离中位数，包含零距离，仅估计一次。固定sigma也在置换前锁定。'
 yield '合并样本SD=0维显式以scale=1保留，中心化后为0；pooled median=0则自动核宽失败，须改明确固定正sigma，不静默加epsilon或跳过零值。'
 yield '两个统计共享同一seed排列；p的+1口径、极端次数、分母、原始统计、全部排列索引和两条置换分布均保留。'
 yield 'p不是迁移概率，有限随机置换有分辨率与Monte Carlo变动；模拟L*a*b*分布变化不是颜色质量或工艺因果判定。两个检验的p未作多重校正，分别复核，不合成为自动迁移结论。'

def _stratified_assumptions(result):
 info=result['stratification']
 yield '按缸分层（by_vat）：同缸色样彼此相关，跨缸打乱会把缸间差异误判为批次迁移；零分布仅由缸内交换批次归属构成，保留各缸两批样本数，不跨缸移动样本。'
 yield '分层抽样依据（已冻结）：'+info['sampling_basis']+' 缸序：'+'、'.join(info['vat_order'])+'；两检验共用同一批缸内排列。'
 yield '分层检验的可交换前提是缸内批次标签条件可交换；缸级系统差异被分层隔离而不再进入零分布。缺缸号或缸内只有一批的数据集在研究冻结与运行时均拒绝。'
 if info['method']=='exact_enumeration':
  yield '本运行使用全枚举精确p：可行分组%d全部计入，观测分配本身属于枚举之一，p=极端次数/%d，不做+1校正；结果对给定数据与口径完全确定。'%(info['feasible_groups'],info['evaluated_groups'])
 else:
  yield '本运行使用固定seed=%d的蒙特卡洛缸内抽样，B=%d，p=(1+极端次数)/(B+1)；重跑同快照同seed结果一致，改变抽样预算需新建口径与研究。'%(result['seed'],result['B'])
