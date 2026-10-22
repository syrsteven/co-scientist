
/* Explicitly synthetic data for interaction testing. Never claim as scientific output. */
window.MONITOR_FIXTURE = (() => {
  const common = {
    assumptions: ["研究对象为极化、成熟的人源 RPE 细胞。", "应激强度不足以造成广泛的急性细胞死亡。"],
    evidence: ["演示占位：此原型没有与具体主张绑定的真实 PubMed 证据。", "正式运行需检查原生文献记录、Source Review 和原文来源。"],
    reflection: ["区分相关性与因果性。", "加入时间序列、反向干预与竞争机制对照。", "核对分子干预是否具备预期靶点特异性。"]
  };
  function C(id,g,title,oneLine,claim,chain,pred,fals,parent=[],operator="root") {
    return {id,g,title,summary:oneLine,claim,mechanism_chain:chain,assumptions:[...common.assumptions],
      predictions:pred,falsifiers:fals,parents:parent,operator,reflection:[...common.reflection],
      evidence:[...common.evidence],source:"synthetic-fixture",createdAt:null,
      raw:{hypothesis_id:id,title,claim,mechanism_chain:chain,assumptions:common.assumptions,predictions:pred,falsifiers:fals,
        generation_index:g,scientific_parent_ids:parent, generation_strategy:operator,notice:"SYNTHETIC_FIXTURE_NOT_SCIENTIFIC_EVIDENCE"}};
  }
  const candidates = [
    C("demo-g0-a",0,"mtDNA–cGAS–STING Feedback","探讨应激后 mtDNA 释放能否引发持续的 cGAS–STING 炎症反馈。",
      "瞬时亚致死线粒体应激可能通过胞质 mtDNA 激活 cGAS–STING，并在清除不足时形成持续炎症状态。",
      ["瞬时线粒体应激","胞质 mtDNA 增加","cGAS–STING 信号激活","持续炎症与恢复受阻"],
      ["应激解除后 mtDNA 泄漏持续时，炎症标志物下降较慢。","特异抑制 DNA 感知通路可能缩短异常炎症持续时间。"],
      ["未观察到细胞质 mtDNA 增加。","STING 缺失不影响后续炎症持续性。"]),
    C("demo-g0-b",0,"mtRNA–MAVS Recovery Switch","研究线粒体 RNA 泄漏是否通过 MAVS 改变 RPE 损伤后恢复。",
      "线粒体双链 RNA 进入胞质后，可能触发 RNA 感知与 MAVS 信号，延迟受损 RPE 的恢复。",
      ["线粒体 RNA 泄漏","RNA 感知通路激活","MAVS 信号持续","细胞功能恢复延迟"],
      ["在相似 DNA 泄漏水平下，RNA 清除干预可改变恢复速度。"],
      ["MAVS 丢失对恢复速度无影响。"]),
    C("demo-g0-c",0,"Lysosomal Clearance Bottleneck","探讨溶酶体酸化受损是否阻碍线粒体自噬并放大炎症。",
      "应激后的溶酶体酸化不足可能导致线粒体自噬停滞，继而放大损伤相关先天免疫信号。",
      ["溶酶体酸化下降","线粒体自噬通量降低","受损线粒体滞留","炎症信号延长"],
      ["恢复酸化能力可提高线粒体清除通量。"],
      ["恢复酸化不改变清除通量或炎症轨迹。"]),
    C("demo-g0-d",0,"Lipid Peroxidation Memory","研究脂质过氧化是否形成 RPE 应激后的持久功能障碍。",
      "氧化应激后的膜脂质过氧化可能独立于核酸感知，驱动 RPE 长期屏障功能下降。",
      ["亚致死氧化应激","膜脂过氧化累积","屏障与吞噬功能受损"],
      ["在核酸感知被抑制后仍存在脂质相关功能损伤。"],
      ["抑制脂质过氧化不改变功能恢复。"]),
    C("demo-g1-a",1,"TBK1–Clearance Stress Relay","探索 DNA 感知与溶酶体清除缺陷之间的反馈耦合。",
      "DNA 感知产生的应激信号可能与溶酶体清除不足互相强化，从而造成 RPE 恢复失败。",
      ["mtDNA 释放与信号激活","清除相关调节改变","受损线粒体滞留","炎症反馈增强"],
      ["双路径干预与单路径干预存在可区分的功能恢复效果。"],
      ["移除其中一条路径后反馈环仍可独立维持。"],["demo-g0-a","demo-g0-c"],"crossover"),
    C("demo-g1-b",1,"RNA Sensing and Autophagic Flux","探索 MAVS 信号和自噬通量在恢复中的先后关系。",
      "RNA 感知与自噬通量的时间关系可能决定 RPE 是恢复还是进入慢性应激状态。",
      ["线粒体 RNA 泄漏","MAVS 及应激信号","自噬通量改变","恢复速度变化"],
      ["RNA 处理与清除干预的顺序会改变最终恢复情况。"],
      ["干预顺序不会造成可重复的恢复差异。"],["demo-g0-b","demo-g0-c"],"crossover"),
    C("demo-g2-a",2,"TBK1–IRF3 Translation Gate","假设 DNA 感知经 TBK1/IRF3 改变线粒体清除能力，维持损伤循环。",
      "在 RPE 应激后，mtDNA–cGAS–STING 信号可能通过 TBK1/IRF3 相关翻译调控影响线粒体清除，从而形成炎症持续的反馈门控。",
      ["胞质 mtDNA 与 STING 激活","TBK1/IRF3 及翻译状态改变","线粒体清除能力下降","mtDNA 再释放和炎症持续"],
      ["TBK1/IRF3 的时间限定干预应同时改变翻译标志与清除通量。","需要区分 DNA-first、RNA-first 与非核酸感知机制。"],
      ["TBK1/IRF3 干预不影响清除通量。","翻译调控在 DNA 感知之后未出现可检测变化。"],["demo-g0-a","demo-g1-a"],"crossover"),
    C("demo-g2-b",2,"Lysosome–Mitochondria Feedback","以清除功能为中心重构先天免疫信号的时序模型。",
      "把先天免疫和溶酶体异常拆分为可检验的因果阶段，比较上游触发与下游放大。",
      ["上游应激感知","清除系统能力变化","功能恢复或二次损伤"],
      ["不同时间点的清除干预出现不同恢复窗口。"],
      ["清除通量与功能恢复之间不存在可重复关联。"],["demo-g1-a"],"mutation"),
    C("demo-g3-a",3,"MAVS–tRNA Alternative Circuit","检验线粒体 RNA 来源是否解释 DNA 感知模型无法解释的现象。",
      "以 MAVS 为中心构建竞争机制，检验 RNA 泄漏是否更能解释某些持久应激轨迹。",
      ["RNA 来源与加工","MAVS 信号响应","清除及屏障功能改变"],
      ["MAVS 特异干预在 DNA 路径干预失败的条件下仍有预测力。"],
      ["MAVS 干预未影响任何预设功能指标。"],["demo-g0-b"],"mutation"),
    C("demo-g3-b",3,"Membrane Damage Competing Pathway","探索膜脂损伤与清除失败能否独立解释长期功能障碍。",
      "将脂质损伤和溶酶体清除缺陷作为 DNA/RNA 感知之外的独立竞争解释。",
      ["脂质过氧化","膜/溶酶体损伤","细胞屏障与吞噬功能异常"],
      ["膜损伤标志物预测某些不依赖核酸感知的恢复失败。"],
      ["脂质损伤完全不能解释独立的功能变化。"],["demo-g0-d","demo-g2-b"],"crossover")
  ];
  const cById=Object.fromEntries(candidates.map(c=>[c.id,c]));
  const steps=[
    {label:"准备研究",g:0,status:"Prepared",minute:0,cost:0,calls:0,summary:"冻结研究目标与执行计划；尚未产生假设。"},
    {label:"G0 开始生成",g:0,status:"Running",minute:80,cost:.08,calls:5,summary:"完成前两条根假设的生成与初步检查。",created:["demo-g0-a","demo-g0-b"]},
    {label:"G0 初代候选",g:0,status:"Running",minute:170,cost:.17,calls:11,summary:"生成其余两条独立研究假设。",created:["demo-g0-c","demo-g0-d"]},
    {label:"文献审阅与反思",g:0,status:"Running",minute:270,cost:.25,calls:18,summary:"模拟检索、Source Review 与 Reflection 已执行。"},
    {label:"G0 第一组 Ranking",g:0,status:"Running",minute:350,cost:.30,calls:23,summary:"完成前两个候选的有效配对比较。"},
    {label:"G0 评价完成",g:0,status:"Running",minute:426,cost:.36,calls:27,summary:"G0 候选完成基础比较，获得暂时评分。"},
    {label:"G1 后代产生",g:1,status:"Running",minute:520,cost:.43,calls:32,summary:"依据已有候选生成两条 G1 Crossover 后代。",created:["demo-g1-a","demo-g1-b"]},
    {label:"G1 评价完成",g:1,status:"Running",minute:618,cost:.50,calls:37,summary:"新候选进入累计池，并完成当前比较。"},
    {label:"G2 后代产生",g:2,status:"Running",minute:705,cost:.57,calls:42,summary:"产生 TBK1–IRF3 与溶酶体机制候选。",created:["demo-g2-a","demo-g2-b"]},
    {label:"G2 Reflection 重试",g:2,status:"Running",minute:766,cost:.62,calls:44,retry:1,summary:"模拟一次无效 JSON；经过有界重试继续执行。",alert:true},
    {label:"G2 评价完成",g:2,status:"Running",minute:832,cost:.71,calls:47,retry:1,summary:"完成 G2 配对比较，临时领先候选可能变化。"},
    {label:"G3 后代产生",g:3,status:"Running",minute:889,cost:.78,calls:49,retry:1,summary:"生成 G3 的 Mutation 与 Crossover 后代。",created:["demo-g3-a","demo-g3-b"]},
    {label:"G3 评价完成",g:3,status:"Running",minute:928,cost:.85,calls:51,retry:1,summary:"完成全部演化后代的当前评价。"},
    {label:"最终选择",g:3,status:"Completed",minute:950,cost:.89,calls:51,retry:1,summary:"模拟终局完成；按累计池最高后验 μ 选择演示 Winner。"}
  ];
  const appearance={};steps.forEach((s,i)=>{(s.created||[]).forEach(id=>appearance[id]=i)});
  candidates.forEach(c=>{c.appear=appearance[c.id]??999});
  const matches=[
    {step:4,a:"demo-g0-a",b:"demo-g0-b",winner:"demo-g0-a",note:"DNA-first 假设在此合成比较中胜出。"},
    {step:4,a:"demo-g0-a",b:"demo-g0-b",winner:"demo-g0-b",note:"反向比较模拟结果。"},
    {step:5,a:"demo-g0-c",b:"demo-g0-d",winner:"demo-g0-c",note:"清除机制的实验可检验性更高（演示判断）。"},
    {step:5,a:"demo-g0-c",b:"demo-g0-d",winner:"demo-g0-c",note:"重复比较用于展示有效次数累计。"},
    {step:7,a:"demo-g1-a",b:"demo-g1-b",winner:"demo-g1-a",note:"跨机制反馈回路优于单一路径（演示判断）。"},
    {step:7,a:"demo-g1-a",b:"demo-g1-b",winner:"demo-g1-a",note:"重复比较使两位新候选满足最低次数。"},
    {step:7,a:"demo-g0-a",b:"demo-g1-a",winner:"demo-g1-a",note:"G1 新候选获得跨代比较。"},
    {step:10,a:"demo-g2-a",b:"demo-g2-b",winner:"demo-g2-a",note:"G2 Translation Gate 机制的可区分预测更明确（演示判断）。"},
    {step:10,a:"demo-g2-a",b:"demo-g2-b",winner:"demo-g2-a",note:"两条 G2 候选完成最低次数。"},
    {step:10,a:"demo-g2-a",b:"demo-g0-c",winner:"demo-g2-a",note:"G2 与 G0 清除模型跨代比较。"},
    {step:12,a:"demo-g3-a",b:"demo-g3-b",winner:"demo-g3-a",note:"G3 竞争机制比较。"},
    {step:12,a:"demo-g3-a",b:"demo-g3-b",winner:"demo-g3-b",note:"反向比较模拟结果。"}
  ];
  const ratings={
    "demo-g0-a":[[4,28.1,7.1],[7,27.9,6.5],[12,27.9,6.5]],
    "demo-g0-b":[[4,24.4,7.1]],
    "demo-g0-c":[[5,29.1,7.0],[10,28.0,6.3]],
    "demo-g0-d":[[5,21.0,7.1]],
    "demo-g1-a":[[7,30.5,6.1]],
    "demo-g1-b":[[7,22.3,7.4]],
    "demo-g2-a":[[10,33.4,6.0]],
    "demo-g2-b":[[10,23.0,7.3]],
    "demo-g3-a":[[12,25.9,7.2]],
    "demo-g3-b":[[12,25.1,7.2]]
  };
  const timelineRaw=steps.map((s,i)=>({
    sequence:i+1,event_type:s.alert?"SIMULATED_OUTPUT_RETRY":s.status==="Completed"?"SIMULATED_FINAL_SELECTION":"SIMULATED_MILESTONE",
    label:s.label,summary:s.summary,minute:s.minute,generation:s.g
  }));
  return {version:"synthetic-monitor-fixture-v2",study:"RPE Mitochondrial Stress",runId:"synthetic-demo-g3-20261022",
    maxGenerations:3, totalSlots:10,candidates,cById,steps,matches,ratings,timelineRaw,finalWinner:"demo-g2-a"};
})();
