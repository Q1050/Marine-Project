from __future__ import annotations
import uuid
from collections import Counter
from datetime import datetime,timedelta,timezone
from sqlalchemy import or_
from jurisdiction_boundary_registry import canonical_json
from models import OccurrenceAcquisitionBatch,OccurrenceAcquisitionBatchItem
from identification_corpus_service import fingerprint
from occurrence_evidence_service import OccurrenceEvidenceService
class OccurrenceBatchService:
 def __init__(self,session):self.session=session
 def prepare(self,region_id,batch_key,items,user_id,configuration=None):
  canonical=sorted([{"jurisdiction_id":int(x["jurisdiction_id"]),"taxon_id":int(x["taxon_id"]),"source_key":x["source_key"]} for x in items],key=lambda x:(x["jurisdiction_id"],x["taxon_id"],x["source_key"]));fp=fingerprint({"region_id":region_id,"batch_key":batch_key,"items":canonical,"configuration":configuration or {}});batch=self.session.query(OccurrenceAcquisitionBatch).filter_by(batch_fingerprint=fp).one_or_none()
  if batch:return batch
  batch=OccurrenceAcquisitionBatch(batch_key=batch_key,region_id=region_id,configuration_json=canonical_json(configuration or {}),batch_fingerprint=fp,created_by_user_id=user_id);self.session.add(batch);self.session.flush();service=OccurrenceEvidenceService(self.session)
  for item in canonical:
   readiness=service.readiness(item["jurisdiction_id"],item["taxon_id"],item["source_key"]);self.session.add(OccurrenceAcquisitionBatchItem(batch_id=batch.id,readiness_state=readiness,workflow_state="PENDING" if readiness=="READY_FOR_ACQUISITION" else "BLOCKED",**item))
  self.session.commit();return batch
 def claim(self,worker,lease_minutes=15):
  now=datetime.now(timezone.utc);q=self.session.query(OccurrenceAcquisitionBatchItem).filter(or_(OccurrenceAcquisitionBatchItem.workflow_state.in_(["PENDING","FAILED"]),OccurrenceAcquisitionBatchItem.lease_expires_at<now)).order_by(OccurrenceAcquisitionBatchItem.id)
  if self.session.bind.dialect.name=="postgresql":q=q.with_for_update(skip_locked=True)
  row=q.first()
  if not row:return None
  row.workflow_state="CLAIMED";row.claim_token=uuid.uuid4().hex;row.claimed_by=worker;row.claimed_at=now;row.lease_expires_at=now+timedelta(minutes=lease_minutes);self.session.commit();return row
 def finish(self,row,token,result=None,error=None):
  if row.claim_token!=token:raise ValueError("Claim token mismatch")
  if error:row.workflow_state="FAILED";row.retry_count+=1;row.last_error=error;row.claim_token=None;row.lease_expires_at=None
  else:
   row.workflow_state="COMPLETED";row.result_json=canonical_json(result or {});row.completed_at=datetime.now(timezone.utc);row.last_error=None;row.claim_token=None;row.lease_expires_at=None;self.session.flush()
   unfinished=self.session.query(OccurrenceAcquisitionBatchItem).filter(OccurrenceAcquisitionBatchItem.batch_id==row.batch_id,OccurrenceAcquisitionBatchItem.workflow_state.not_in(["COMPLETED","BLOCKED"])).count()
   if not unfinished:
    batch=self.session.get(OccurrenceAcquisitionBatch,row.batch_id);batch.workflow_state="COMPLETED";batch.completed_at=datetime.now(timezone.utc)
  self.session.commit();return row
 def summary(self,batch_id):
  rows=self.session.query(OccurrenceAcquisitionBatchItem).filter_by(batch_id=batch_id).all();return {"batch_id":batch_id,"total":len(rows),"workflow_states":dict(Counter(r.workflow_state for r in rows)),"readiness":dict(Counter(r.readiness_state for r in rows)),"items":[{"id":r.id,"jurisdiction_id":r.jurisdiction_id,"taxon_id":r.taxon_id,"source_key":r.source_key,"readiness":r.readiness_state,"state":r.workflow_state,"retry_count":r.retry_count,"last_error":r.last_error} for r in rows]}
