export const groups = [
  ["goal","研究目标","定义问题与产出","研究配置"],
  ["model","模型连接","供应商、模型与生成参数","研究配置"],
  ["literature","文献检索","证据内容与检索策略","研究配置"],
  ["review","评审与演化","准入标准与改进轮次","运行策略"],
  ["ranking","竞技场与停止","排名规模与收敛窗口","运行策略"],
  ["budget","计算预算","费用、调用与规模上限","运行策略"],
  ["interface","界面偏好","刷新频率与阅读密度","本地工作台"],
];
export const preferenceDefaults={pollSeconds:5,autoRefresh:true,density:"comfortable"};
export function preferences(value={}) {
  return {pollSeconds:[5,10,30,60].includes(Number(value.pollSeconds))?Number(value.pollSeconds):5,
    autoRefresh:typeof value.autoRefresh==="boolean"?value.autoRefresh:true,
    density:value.density==="compact"?"compact":"comfortable"};
}
export const clone = value => JSON.parse(JSON.stringify(value));
const metaDefaults={max_rounds:0,match_interval:2,max_children_per_round:1};
function profileDraft(profile){return {...clone(profile),meta_review:clone(profile.meta_review??metaDefaults)};}
const forbidden=new Set(["__proto__","prototype","constructor"]);
export function getPath(object,path) {return path.split(".").reduce((v,k)=>forbidden.has(k)?undefined:v?.[k],object);}
export function setPath(object,path,value) {
  const parts=path.split(".");if(parts.some(k=>forbidden.has(k)))throw new Error("Invalid field path");
  const last=parts.pop();let target=object;
  for(const part of parts){if(!target[part]||typeof target[part]!=="object")target[part]={};target=target[part];}
  target[last]=value;
}
export function fromTemplate(template,providerInfo) {
  return {name:`${template.id} 研究配置`,goal:clone(template.goal),profile:profileDraft(template.profile),model:providerInfo?.model||""};
}
export function switchProvider(draft,provider,templates,providerInfo) {
  const next=clone(draft),template=templates.find(t=>t.id===provider);
  if(!template)throw new Error("未知供应商");
  const wasReplay=next.profile.providers.llm==="replay";
  next.profile.providers=clone(template.profile.providers);
  if(provider!=="deepseek")delete next.profile.ranking_output_protocol;
  next.profile.replay_resources=clone(template.profile.replay_resources);
  if(provider==="replay"){
    next.profile.literature_content="metadata";
    next.profile.scientific_context=false;
    next.profile.research_protocol_version=null;
    next.profile.evolution.max_rounds=0;
    next.profile.meta_review=clone(metaDefaults);
    next.model="";
  }else {
    if(wasReplay){
      next.profile.scientific_context=template.profile.scientific_context;
      next.profile.research_protocol_version=template.profile.research_protocol_version??null;
      next.profile.literature_content=template.profile.literature_content;
      next.profile.literature_sort=template.profile.literature_sort;
      next.profile.meta_review=clone(template.profile.meta_review??metaDefaults);
      if(template.profile.evolution)next.profile.evolution=clone(template.profile.evolution);
    }
    next.model=providerInfo?.model||"";
  }
  return next;
}
export function fromRun(data) {
  if(!data?.manifest?.profile||!data.manifest.goal)throw new Error("当前运行缺少配置快照");
  return {name:`${data.manifest.run_id} 的副本`.slice(0,80),goal:clone(data.manifest.goal),
    profile:profileDraft(data.manifest.profile),model:data.manifest.provider_configuration?.model||""};
}
export function errorsByGroup(errors) {
  const result={};
  for(const error of errors){const p=error.field||"";
    const group=p.startsWith("goal.")?"goal":p==="model"||p.startsWith("profile.providers")?"model":
      /profile\.(literature_content|literature_sort|literature_search_queries|scientific_context)/.test(p)?"literature":
      p==="profile.research_protocol_version"?"review":
      /profile\.(review|meta_review|evolution|literature_novelty|duplicate)/.test(p)?"review":
      /profile\.(stop|tournament|ranking_output_protocol)/.test(p)?"ranking":p.startsWith("profile.budget")?"budget":"goal";
    result[group]=(result[group]||0)+1;
  }
  return result;
}
export function dirtyFingerprint(draft){return JSON.stringify(draft);}

export function listedModels(catalog,provider){return (catalog?.models||[]).filter(m=>m.provider===provider);}
export function modelReference(catalog,provider,id){return listedModels(catalog,provider).find(m=>m.id===id)||null;}
export function priceNumber(value){return value==null?"未列出":Number(value).toLocaleString("en-US",{maximumFractionDigits:6});}
