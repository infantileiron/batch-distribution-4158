import type {Result} from '../types/domain';import {num} from '../utils/format';
export function StratificationPanel({result}:{result:Result}){
 const info=result.stratification;
 if(!info)return null;
 return <section className="stratification-panel">
  <p className="eyebrow">STRATIFIED PERMUTATION / {info.method==='exact_enumeration'?'EXACT ENUMERATION':'MONTE CARLO'}</p>
  <h2>按缸分层 · 仅缸内交换批次归属</h2>
  <div className="policy-strip">
   <span>方式 <b>{info.method==='exact_enumeration'?'全枚举精确p':'随机抽样 +1 口径'}</b></span>
   <span>可行分组 <b>{num(info.feasible_groups,0)}</b></span>
   <span>预算 <b>{num(info.exact_budget,0)}</b></span>
   <span>实际计入 <b>{num(info.evaluated_groups,0)}</b></span>
   <span>缸数 <b>{info.vats.length}</b></span>
   <span>共享排列 <b>{info.shared_permutations?'是':'否'}</b></span>
  </div>
  <p className="sampling-basis">{info.sampling_basis}</p>
  <div className="table-scroll"><table>
   <thead><tr><th>缸号（冻结缸序）</th><th>缸内总数</th><th>A批</th><th>B批</th><th>缸内可行分组 C(n,n_A)</th></tr></thead>
   <tbody>{info.vats.map(v=><tr key={v.vat_id}><td>{v.vat_id}</td><td>{v.n_total}</td><td>{v.n_a}</td><td>{v.n_b}</td><td>{num(v.feasible_groups,0)}</td></tr>)}</tbody>
  </table></div>
  <p className="muted">各缸两批样本数在每次排列中保持不变，样本不跨缸移动；全枚举时观测分配本身计入分母，蒙特卡洛按+1口径校正。分层与抽样依据随运行快照冻结，CSV同步留痕。</p>
 </section>;
}
