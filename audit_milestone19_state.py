"""Read-only Milestone 19 production-state summary."""
import json
from sqlalchemy import func, text
from database import SessionLocal
from identification_corpus_service import IdentificationCorpusService
from models import (AnomalyAssessment,AnomalyConfiguration,EcologicalStatusAssertion,GovernedOccurrenceEvidence,HistoricalOccurrence,IdentificationBenchmarkRun,IdentificationCorpus,IdentificationMediaAsset,IdentificationMediaSource,LocalTaxonCandidate,Observation,RegionalTaxonManifestRun,RegionalTaxonRegistry,SpeciesProgram,SuitabilityDeployment,TrainingRun)

def main():
 session=SessionLocal()
 try:
  models=[Observation,HistoricalOccurrence,GovernedOccurrenceEvidence,EcologicalStatusAssertion,RegionalTaxonRegistry,SpeciesProgram,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalyConfiguration,IdentificationMediaAsset,IdentificationCorpus,IdentificationBenchmarkRun,LocalTaxonCandidate,RegionalTaxonManifestRun]
  result={"counts":{model.__tablename__:session.query(model).count() for model in models},"assets_by_provider":[{"provider":provider,"assets":count,"bytes":int(size)} for provider,count,size in session.query(IdentificationMediaSource.scientific_provider,func.count(IdentificationMediaAsset.id),func.coalesce(func.sum(IdentificationMediaAsset.size_bytes),0)).outerjoin(IdentificationMediaAsset).group_by(IdentificationMediaSource.id).all()],"quality":dict(session.query(IdentificationMediaAsset.quality_state,func.count()).group_by(IdentificationMediaAsset.quality_state).all()),"review":dict(session.query(IdentificationMediaAsset.review_state,func.count()).group_by(IdentificationMediaAsset.review_state).all()),"retried":[{"asset_id":asset.id,"retry_count":asset.acquisition_retry_count,"last_error":asset.acquisition_last_error,"quality":asset.quality_state} for asset in session.query(IdentificationMediaAsset).filter(IdentificationMediaAsset.acquisition_retry_count>0)],"review_progress":IdentificationCorpusService(session).review_progress(1),"unvalidated_foreign_keys":session.execute(text("SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated")).scalar()}
  print(json.dumps(result,indent=2,default=str))
 finally:session.close()
if __name__=="__main__":main()
