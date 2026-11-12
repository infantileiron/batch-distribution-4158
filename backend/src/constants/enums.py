ROLES=('admin','analyst','viewer')
SCALINGS=('none','pooled_std')
BANDWIDTHS=('fixed','pooled_median')
# pooled：全部样本跨缸打乱（历史口径）；by_vat：仅缸内交换批次归属的分层检验
STRATIFICATIONS=('pooled','by_vat')
RUN_STATUSES=('queued','running','completed','failed')
REVIEW_DECISIONS=('accepted','needs_changes')
