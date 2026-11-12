import math,re

def validate_dataset(batch_a,batch_b):
 seen=set()
 for label,rows in (('A',batch_a),('B',batch_b)):
  if not 4<=len(rows)<=120:raise ValueError('每批须4至120条独立模拟读数')
  for row in rows:
   key=row['sample_id']
   if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,30}',key) or key in seen:raise ValueError('样本ID须跨两批唯一且为英数短ID')
   seen.add(key)
   if not all(math.isfinite(row[k]) for k in ('l','a','b')):raise ValueError('L*a*b*须有限，不能填补缺读数')
 return True

_VAT_RE=re.compile(r'[A-Za-z0-9][A-Za-z0-9_ -]{0,30}')

def validate_vat_groups(batch_a,batch_b):
 """按缸分层（by_vat）前置校验：缸号不得缺失，且每缸两批都至少各有一条。"""
 groups={}
 for label,rows in (('A',batch_a),('B',batch_b)):
  for row in rows:
   vat=row.get('vat_id')
   if vat is None or not str(vat).strip():raise ValueError('按缸分层检验要求每条读数提供缸号vat_id；存在缺缸号样本，拒绝运行')
   vat=str(vat).strip()
   if not _VAT_RE.fullmatch(vat):raise ValueError('缸号须为1至31位英数/空格/下划线/短横线且以英数开头')
   groups.setdefault(vat,set()).add(label)
 missing=[vat for vat,labels in sorted(groups.items()) if {'A','B'}-labels]
 if missing:raise ValueError('缸内只有一批样本，无法缸内交换归属，拒绝运行；问题缸号：'+'、'.join(missing))
 if len(groups)<2:raise ValueError('按缸分层检验至少需要两个缸以分离缸间差异；当前缸数：%d'%len(groups))
 return sorted(groups)
