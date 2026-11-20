from __future__ import annotations
import io, json, uuid, os, hmac
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
import joblib, numpy as np, pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import *
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, GradientBoostingClassifier, HistGradientBoostingClassifier, RandomForestRegressor, ExtraTreesRegressor, GradientBoostingRegressor, HistGradientBoostingRegressor
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor

BASE=Path(__file__).resolve().parents[1]
for name in ('data','models','experiments'): (BASE/name).mkdir(exist_ok=True)
app=FastAPI(title='Open ML Studio API',version='3.1.0',description='Advanced general-purpose tabular ML workbench')
from .advanced import router as advanced_router
app.include_router(advanced_router)
@app.middleware("http")
async def require_app_password(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        configured = os.getenv("APP_PASSWORD", "")
        supplied = request.headers.get("X-App-Password", "")
        if not configured:
            return JSONResponse(status_code=503, content={"detail": "Service is not configured. Set APP_PASSWORD in the hosting environment."})
        if not supplied or not hmac.compare_digest(supplied, configured):
            return JSONResponse(status_code=401, content={"detail": "Access password is missing or incorrect."})
    return await call_next(request)
DATASETS:dict[str,pd.DataFrame]={}; MODELS:dict[str,dict]={}; EXPERIMENTS:dict[str,dict]={}
class TrainRequest(BaseModel):
 dataset_id:str; target:str; task:str=Field(pattern='^(classification|regression)$')
 algorithms:list[str]=['logistic','random_forest','extra_trees']; test_size:float=Field(.2,gt=.05,lt=.5)
 split_strategy:str=Field('random',pattern='^(random|chronological)$'); random_state:int=42
 selected_features:list[str]|None=None
class PredictRequest(BaseModel): model_id:str; records:list[dict[str,Any]]
def getdf(i):
 if i not in DATASETS: raise HTTPException(404,'Dataset missing from this API session; upload it again.')
 return DATASETS[i]
def profile(df):
 return {'rows':len(df),'columns':len(df.columns),'duplicate_rows':int(df.duplicated().sum()),'memory_mb':round(df.memory_usage(deep=True).sum()/1048576,3),'column_profile':[{'name':str(c),'dtype':str(df[c].dtype),'numeric':bool(pd.api.types.is_numeric_dtype(df[c])),'missing':int(df[c].isna().sum()),'missing_pct':round(df[c].isna().mean()*100,2),'unique':int(df[c].nunique()),'examples':[str(x)[:70] for x in df[c].dropna().head(4)]} for c in df.columns]}
@app.get('/api/health')
def health(): return {'status':'ok','version':'3.0.0','engine':'scikit-learn','utc':datetime.now(timezone.utc).isoformat()}
@app.post('/api/datasets')
async def upload(file:UploadFile=File(...)):
 if not file.filename.lower().endswith('.csv'): raise HTTPException(400,'Upload a CSV file.')
 raw=await file.read()
 if len(raw)>100*1024*1024: raise HTTPException(413,'Maximum CSV size is 100 MB.')
 try: df=pd.read_csv(io.BytesIO(raw),sep=None,engine='python',low_memory=False)
 except Exception as e: raise HTTPException(400,f'CSV parse failed: {e}')
 if len(df)<2 or len(df.columns)<2: raise HTTPException(400,'CSV needs at least two columns and two rows.')
 if len(df)>500000: raise HTTPException(400,'Maximum supported rows: 500,000.')
 df.columns=[str(c).strip() for c in df.columns]
 if len(set(df.columns))!=len(df.columns): raise HTTPException(400,'Column names must be unique.')
 did=uuid.uuid4().hex[:12]; DATASETS[did]=df
 (BASE/'data'/f'{did}_upload.csv').write_bytes(raw)
 return {'dataset_id':did,'filename':file.filename,**profile(df)}
@app.get('/api/datasets/{did}')
def get_profile(did:str): return {'dataset_id':did,**profile(getdf(did))}
def estimator(name,task,seed):
 c={'logistic':LogisticRegression(max_iter=1500,class_weight='balanced'),'random_forest':RandomForestClassifier(n_estimators=200,min_samples_leaf=2,n_jobs=-1,class_weight='balanced_subsample',random_state=seed),'extra_trees':ExtraTreesClassifier(n_estimators=200,min_samples_leaf=2,n_jobs=-1,class_weight='balanced',random_state=seed),'gradient_boosting':GradientBoostingClassifier(random_state=seed),'hist_gradient_boosting':HistGradientBoostingClassifier(max_iter=120,random_state=seed),'decision_tree':DecisionTreeClassifier(max_depth=8,min_samples_leaf=3,class_weight='balanced',random_state=seed),'knn':KNeighborsClassifier(n_neighbors=7,weights='distance')} if task=='classification' else {'ridge':Ridge(),'random_forest':RandomForestRegressor(n_estimators=200,min_samples_leaf=2,n_jobs=-1,random_state=seed),'extra_trees':ExtraTreesRegressor(n_estimators=200,min_samples_leaf=2,n_jobs=-1,random_state=seed),'gradient_boosting':GradientBoostingRegressor(random_state=seed),'hist_gradient_boosting':HistGradientBoostingRegressor(max_iter=120,random_state=seed),'decision_tree':DecisionTreeRegressor(max_depth=8,min_samples_leaf=3,random_state=seed),'knn':KNeighborsRegressor(n_neighbors=7,weights='distance')}
 if name not in c: raise HTTPException(400,f'Unsupported algorithm: {name}')
 return c[name]
def pipeline(X,model):
 nums=X.select_dtypes(include=['number','bool']).columns.tolist(); cats=[c for c in X.columns if c not in nums]; trans=[]
 if nums: trans.append(('num',Pipeline([('impute',SimpleImputer(strategy='median')),('scale',StandardScaler())]),nums))
 if cats: trans.append(('cat',Pipeline([('impute',SimpleImputer(strategy='most_frequent')),('onehot',OneHotEncoder(handle_unknown='ignore',min_frequency=2))]),cats))
 return Pipeline([('prep',ColumnTransformer(trans,sparse_threshold=0.0)),('model',model)])
@app.post('/api/train')
def train(q:TrainRequest):
 df=getdf(q.dataset_id).copy()
 if q.target not in df: raise HTTPException(400,'Target column not found.')
 feats=[c for c in (q.selected_features or [c for c in df if c!=q.target]) if c in df and c!=q.target]
 if not feats: raise HTTPException(400,'Select at least one feature.')
 d=df[feats+[q.target]].replace([np.inf,-np.inf],np.nan).dropna(subset=[q.target])
 X=d[feats]; y=d[q.target]
 if q.task=='regression':
  y=pd.to_numeric(y,errors='coerce'); ok=y.notna(); X=X.loc[ok]; y=y.loc[ok]
  if y.nunique()<2: raise HTTPException(400,'Regression target must be numeric with at least two values.')
 else:
  y=y.astype(str)
  if y.nunique()<2 or y.nunique()>50: raise HTTPException(400,'Classification requires 2–50 target classes.')
 if len(X)<30: raise HTTPException(400,'At least 30 labelled rows are required.')
 strat=y if q.task=='classification' and q.split_strategy=='random' and y.value_counts().min()>=2 else None
 if q.split_strategy=='chronological':
  cut=int(len(X)*(1-q.test_size)); Xtr,Xte=X.iloc[:cut],X.iloc[cut:]; ytr,yte=y.iloc[:cut],y.iloc[cut:]
 else:
  try: Xtr,Xte,ytr,yte=train_test_split(X,y,test_size=q.test_size,random_state=q.random_state,stratify=strat)
  except ValueError as e: raise HTTPException(400,str(e))
 if q.task=='classification' and ytr.nunique()<2: raise HTTPException(400,'Training split contains only one class.')
 eid=uuid.uuid4().hex[:12]; results=[]
 for alg in q.algorithms:
  try:
   pipe=pipeline(Xtr,estimator(alg,q.task,q.random_state)); pipe.fit(Xtr,ytr); pred=pipe.predict(Xte); m=pipe.named_steps['model']
   if q.task=='classification':
    classes=list(m.classes_); proba=pipe.predict_proba(Xte) if hasattr(pipe,'predict_proba') else None
    metrics={'accuracy':float(accuracy_score(yte,pred)),'balanced_accuracy':float(balanced_accuracy_score(yte,pred)),'precision_weighted':float(precision_score(yte,pred,average='weighted',zero_division=0)),'recall_weighted':float(recall_score(yte,pred,average='weighted',zero_division=0)),'f1_weighted':float(f1_score(yte,pred,average='weighted',zero_division=0)),'confusion_matrix':confusion_matrix(yte,pred,labels=classes).tolist(),'classes':[str(x) for x in classes],'majority_baseline_accuracy':float(yte.value_counts(normalize=True).max())}
    try:
     if proba is not None and len(classes)==2: metrics.update({'roc_auc':float(roc_auc_score(yte,proba[:,1])),'log_loss':float(log_loss(yte,proba,labels=classes)),'brier_score':float(brier_score_loss((np.asarray(yte)==classes[1]).astype(int),proba[:,1]))})
     elif proba is not None: metrics.update({'roc_auc_ovr_weighted':float(roc_auc_score(yte,proba,multi_class='ovr',average='weighted',labels=classes)),'log_loss':float(log_loss(yte,proba,labels=classes))})
    except Exception: pass
    rank=metrics['f1_weighted']
   else:
    rmse=float(np.sqrt(mean_squared_error(yte,pred))); metrics={'mae':float(mean_absolute_error(yte,pred)),'rmse':rmse,'median_absolute_error':float(median_absolute_error(yte,pred)),'r2':float(r2_score(yte,pred)),'baseline_mean_rmse':float(np.sqrt(np.mean((np.asarray(yte)-np.mean(yte))**2)))}; rank=-rmse
   mid=uuid.uuid4().hex[:12]; joblib.dump(pipe,BASE/'models'/f'{mid}.joblib'); MODELS[mid]={'pipeline':pipe,'features':feats,'task':q.task,'target':q.target,'algorithm':alg,'classes':[str(x) for x in m.classes_] if q.task=='classification' else None}
   try:
    pi=permutation_importance(pipe,Xte,yte,n_repeats=4,random_state=q.random_state,n_jobs=-1,scoring='f1_weighted' if q.task=='classification' else 'neg_root_mean_squared_error')
    importance=sorted([{'feature':str(f),'importance_mean':float(v),'importance_std':float(s)} for f,v,s in zip(feats,pi.importances_mean,pi.importances_std)],key=lambda x:abs(x['importance_mean']),reverse=True)
   except Exception: importance=[]
   results.append({'algorithm':alg,'status':'success','model_id':mid,'metrics':metrics,'feature_importance':importance,'_rank':rank})
  except Exception as e: results.append({'algorithm':alg,'status':'failed','error':str(e)[:400]})
 good=[r for r in results if r['status']=='success']
 if not good: raise HTTPException(400,'All algorithms failed: '+'; '.join(x.get('error','') for x in results))
 best=max(good,key=lambda r:r['_rank']);
 for r in results: r.pop('_rank',None)
 record={'experiment_id':eid,'created_at':datetime.now(timezone.utc).isoformat(),'dataset_id':q.dataset_id,'target':q.target,'task':q.task,'features':feats,'split_strategy':q.split_strategy,'train_rows':len(Xtr),'test_rows':len(Xte),'best_algorithm':best['algorithm'],'best_model_id':best['model_id'],'results':results}
 EXPERIMENTS[eid]=record;(BASE/'experiments'/f'{eid}.json').write_text(json.dumps(record,indent=2))
 return record
@app.post('/api/predict')
def predict(q:PredictRequest):
 if q.model_id not in MODELS: raise HTTPException(404,'Model is not in the current API session. Retrain after restarting the API.')
 m=MODELS[q.model_id]; X=pd.DataFrame(q.records)
 missing=[c for c in m['features'] if c not in X]
 if missing: raise HTTPException(400,f'Missing features: {missing}')
 X=X[m['features']]; pred=m['pipeline'].predict(X)
 out={'predictions':[x.item() if hasattr(x,'item') else x for x in pred]}
 if m['task']=='classification' and hasattr(m['pipeline'],'predict_proba'): out.update({'probabilities':m['pipeline'].predict_proba(X).tolist(),'classes':m['classes']})
 return out
@app.get('/api/experiments')
def experiments(): return sorted(EXPERIMENTS.values(),key=lambda x:x['created_at'],reverse=True)
@app.get('/api/models')
def models(): return [{'model_id':k,**{a:b for a,b in v.items() if a!='pipeline'}} for k,v in MODELS.items()]
@app.get('/')
def root(): return FileResponse(BASE/'frontend'/'index.html')
