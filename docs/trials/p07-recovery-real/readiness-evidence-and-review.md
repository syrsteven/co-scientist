# P07恢复：逐项依据与调用后审阅

**Codex 初审，待独立人工复核；science_validated=false。**

模型决定：ready。仅指允许范围的条件性探索准备，不授权执行生成。

与 requested_specificity 一致：可准备提出不预选具体核孔蛋白或模型、明确标注未知关系的条件性探索机制及检验思路，并保留实际锚点、情境差异、竞争解释和检索范围。不得把未知修饰或因果链写成事实，不得据当前阅读给出未经核实的实验参数、可行性保证或新颖性结论。本次在背景判断处停止，不进入生成。

## goal_interpretable

模型 met=True；Goal 要求围绕核孔蛋白磷酸化解释 ALS 相关过程，并提出机制与检验实验；种子明确以“若检测到”为条件，比较参与输出障碍、损伤后反应及并行变化。保留核孔蛋白磷酸化问题、不预选分子或模型的约束清楚，无需改写 Goal。

Codex初审：Goal/固定Brief和seed可追溯，保留核孔蛋白磷酸化、不预选分子或模型；“若检测到”是条件，不承认修饰在ALS中已获测量。

- `997d55886d634f289612ba79e1755f16`：fixed_goal
- `seed-f87361b21b4f44609dedfa2ac9afc7bc-0`：seed

## anchor_traceable

模型 met=True；实际锚点包括 ANXA11 聚集相关的核孔蛋白分布、mRNA 输出及毒性表型，非 ALS 情境中的 TPR 位点磷酸化，以及 SUN1 修饰与相互作用变化。ANXA11 记录中的明确磷酸化对象是 TDP-43；TDP-43 核输入无差异结果也可追溯，均未被替换成核孔蛋白修饰证据。

Codex初审：引用存在且可定位原卡/原文。ANXA11表型、TDP-43修饰/核输入、TPR位点修饰、SUN1邻近输出关系的对象不同；锚点可追溯不表示核孔蛋白磷酸化的ALS因果链成立。

- `finding-f49335ad41a946f9aed8103f53f328ca-6`：finding_and_original_span
  原文 `epmc:PPR:PPR1217875` / view `75bf96a0e25b4e6aa10e54f6781a5382` 字符[1212, 1411]：Consistently, ANXA11 aggregation was associated with nuclear envelope abnormalities, altered nucleoporin distribution, impaired mRNA export, and progressive neuronal toxicity in iPSC-derived neurons.
- `finding-f49335ad41a946f9aed8103f53f328ca-4`：finding_and_original_span
  原文 `epmc:PPR:PPR1217875` / view `75bf96a0e25b4e6aa10e54f6781a5382` 字符[827, 1016]：Strikingly, ANXA11 fibrils induces pathological conversion of TDP-43, including hyperphosphorylation, accumulation in detergent-insoluble fractions, and formation of cytoplasmic aggregates.
- `finding-f8cf38bfaf564f93a51f5b4b17aeefeb-1`：finding_and_original_span
  原文 `epmc:MED:35112738` / view `876e76bb00f84e928a89cbea813dacad` 字符[1336, 1470]：We examined reporters containing the different TDP‐43 variants (Wt, 12D, 12A) and found that their import rates were indistinguishable
- `finding-b8a3fb022bee44afa29c341c2b9115d7-2`：finding_and_original_span
  原文 `epmc:MED:42031697` / view `af80cf113c514689a5b9e25ef9f0b193` 字符[821, 1043]：Using a novel phospho-specific monoclonal antibody, we show that TPR is phosphorylated at Ser2155 following EGFR activation via the canonical RAS-RAF-MEK-ERK MAPK cascade, placing TPR downstream of MAPK pathway activation.
- `finding-61730f7691fd43a8a2b9c92eb6126f3b-2`：finding_and_original_span
  原文 `epmc:MED:28831067` / view `692ca660eef14f86a19318ca2e08d85b` 字符[340, 518]：The SUN1-NXF1 association is at least partly regulated by a protein kinase C (PKC) which phosphorylates serine 113 (S113) in the N-terminal domain leading to reduced interaction.

## context_preserved

模型 met=True；培养神经元、SH-SY5Y、HeLa/U2OS、SOD1 相关材料、免疫及肿瘤情境分别保留，未合并成同一实验或共同因果链。SUN1 是内核膜/LINC 蛋白，其结果不替代核孔蛋白自身的修饰；邻近富集、丰度、定位、蛋白输入与 mRNA 输出也未被视为等价终点。

Codex初审：模型以5份阅读为据判met=true，但这不是独立确认所有体系归属。原宽P04曾有HeLa/U2OS情境配对疑点，P05虽有拆分声明，仍需专家逐句复核；不能因P07ready抹去历史疑点。

- `p04-v2-control-single`：reading
- `p04-v2-complement-single`：reading
- `directed-seed-p04-source-1-single`：reading
- `directed-seed-p04-source-2-single`：reading
- `directed-seed-p04-source-3-single`：reading

## alternatives_considered

模型 met=True；已明确考虑修饰参与障碍、损伤后或适应性反应、共同上游驱动的并行变化，以及不依赖该修饰的核孔组分、运输因子和表达调控变化。聚集体邻近富集、上游 SOD1 降低及 TPR 耗减均未被当作修饰选择性因果证据。

Codex初审：packet存在参与/继发或适应性/共同上游并行解释，且保留剂量、分布、运输因子、表达调控等替代过程。P07没有将其写成已证明的机制，也没有因桥接未知阻断条件性探索。

- `directed-seed-p05-packet-single`：saved_seed_background_packet
- `finding-f49335ad41a946f9aed8103f53f328ca-5`：finding_and_original_span
  原文 `epmc:PPR:PPR1217875` / view `75bf96a0e25b4e6aa10e54f6781a5382` 字符[1017, 1211]：TurboID proximity-labeling proteomics further revealed aggregation-dependent enrichment of nuclear pore complex and nucleocytoplasmic transport factors in the ANXA11 aggregate-proximal proteome.
- `finding-c24e29a61d8a4b999f29c45aa9906729-1`：finding_and_original_span
  原文 `epmc:MED:41691309` / view `ef0d631b44e14b2abf8f10443c55d5c2` 字符[850, 956]：Mutant SOD1 also lowers the abundance of FG-Nups at the nuclear pore without altering nuclear circularity.
- `finding-c24e29a61d8a4b999f29c45aa9906729-3`：finding_and_original_span
  原文 `epmc:MED:41691309` / view `ef0d631b44e14b2abf8f10443c55d5c2` 字符[1134, 1305]：Importantly, AAV-mediated reduction of mutant SOD1 in transgenic mice restored nuclear XPO1 localization, underscoring the causal role of mutant SOD1 in NCT abnormalities.
- `finding-b8a3fb022bee44afa29c341c2b9115d7-0`：finding_and_original_span
  原文 `epmc:MED:42031697` / view `af80cf113c514689a5b9e25ef9f0b193` 字符[469, 687]：Transcriptomic profiling reveals that TPR depletion reshapes EGF-induced, MAPK-responsive gene expression, including altered expression of MAPK pathway components and enhanced induction of the immediate-early gene FOS.

## critical_reading_adequate

模型 met=True；阅读已区分作者观察、解释与跨情境类比，并保留无差异、较弱恢复和异质性结果。SUN1 的结合降低与高效输出未被拼接成同条件配对终点；磷酸模拟、蛋白耗减及通路抑制未被等同于真实修饰的选择性改变。摘要及局部正文的访问边界明确，足以支撑当前探索性范围，但不支撑详细方法参数或科学验证结论。

Codex初审：阴性和条件边界有可定位记录；但P05仍弱化ANXA11作者“induces”和SUN1“leading to reduced interaction”措辞。P07未指出这些问题，故其met=true只是单模型对探索范围的判断，不是科学阅读准确性验收。S113A较弱恢复不等于无效，SUN1对象与磷酸模拟不能替代Nup真实修饰。

- `p04-v2-complement-single`：reading
- `finding-c24e29a61d8a4b999f29c45aa9906729-1`：finding_and_original_span
  原文 `epmc:MED:41691309` / view `ef0d631b44e14b2abf8f10443c55d5c2` 字符[850, 956]：Mutant SOD1 also lowers the abundance of FG-Nups at the nuclear pore without altering nuclear circularity.
- `finding-61730f7691fd43a8a2b9c92eb6126f3b-3`：finding_and_original_span
  原文 `epmc:MED:28831067` / view `692ca660eef14f86a19318ca2e08d85b` 字符[519, 751]：The phosphorylation appears to be important for the SUN1 function in nuclear mRNA export since GFP-SUN1 carrying a S113A mutation was less efficient in restoring mRNA export after SUN1 knockdown as compared to the wild type protein.
- `finding-61730f7691fd43a8a2b9c92eb6126f3b-4`：finding_and_original_span
  原文 `epmc:MED:28831067` / view `692ca660eef14f86a19318ca2e08d85b` 字符[752, 861]：By contrast, GFP-SUN1-S113D resembling the phosphorylated state allowed very efficient export of poly(A)+RNA.
- `finding-61730f7691fd43a8a2b9c92eb6126f3b-6`：finding_and_original_span
  原文 `epmc:MED:28831067` / view `692ca660eef14f86a19318ca2e08d85b` 字符[1018, 1188]：This effect might be independent of SUN1 as expression of a GFP tagged SUN-domain deficient SUN1, which no longer can interact with Nesprin-2, did not affect mRNA export.
- `finding-b8a3fb022bee44afa29c341c2b9115d7-10`：finding_and_original_span
  原文 `epmc:MED:42031697` / view `af80cf113c514689a5b9e25ef9f0b193` 字符[1734, 1880]：heterogeneous phosphorylation patterns in triple-negative breast cancer, two tumor types frequently characterized by MAPK pathway hyperactivation.

## closest_prior_work_attempted

模型 met=True；已有可追溯的 ALS—核孔、核孔—磷酸化—RNA 输出，以及核孔—磷酸化—时序/干预检索尝试，并对返回的相关近邻工作形成实际阅读记录。该条件要求已尝试寻找近邻研究，而非证明检索穷尽或全球新颖；第三条检索首页主要来自其他生物学情境，其适用性限制已保留。

Codex初审：3条实际主题查询和3份新阅读可追溯，符合“尝试过”而非穷尽；每条仅首5项，第三查询未形成新阅读，不能称最接近工作均已定位。两旧精确ID查询不能作为主题覆盖；没有全球不存在/新颖性证明。

- `directed-seed-search-1-page1`：executed_search
  实际查询：(TITLE_ABS:"amyotrophic lateral sclerosis" OR TITLE_ABS:ALS OR TITLE_ABS:"motor neuron disease") AND (TITLE_ABS:nucleoporin* OR TITLE_ABS:"nuclear pore")；返回5/121，scope_complete=False
- `directed-seed-search-2-page1`：executed_search
  实际查询：(TITLE_ABS:nucleoporin* OR TITLE_ABS:"nuclear pore") AND (TITLE_ABS:phosphorylat* OR TITLE_ABS:dephosphorylat* OR TITLE_ABS:phosphosite* OR TITLE_ABS:phosphoproteom* OR TITLE_ABS:phosphomimetic*) AND (TITLE_ABS:"mRNA export" OR TITLE_ABS:"messenger RNA export" OR TITLE_ABS:"RNA export" OR TITLE_ABS:"poly(A) RNA")；返回5/9，scope_complete=False
- `directed-seed-search-3-page1`：executed_search
  实际查询：(TITLE_ABS:nucleoporin* OR TITLE_ABS:"nuclear pore") AND (TITLE_ABS:phosphorylat* OR TITLE_ABS:dephosphorylat* OR TITLE_ABS:phosphosite* OR TITLE_ABS:phosphoproteom* OR TITLE_ABS:phosphomimetic*) AND (TITLE_ABS:"time course" OR TITLE_ABS:"time-course" OR TITLE_ABS:temporal OR TITLE_ABS:longitudinal OR TITLE_ABS:rescue OR TITLE_ABS:reversib* OR TITLE_ABS:phosphomimetic* OR TITLE_ABS:phosphodeficient* OR TITLE_ABS:nonphosphorylatable OR TITLE_ABS:mutagenesis OR TITLE_ABS:kinase* OR TITLE_ABS:phosphatase* OR TITLE_ABS:inhibitor*)；返回5/184，scope_complete=False
- `directed-seed-p04-source-1-single`：reading
- `directed-seed-p04-source-2-single`：reading
- `directed-seed-p04-source-3-single`：reading

## 未解除的边界

原Attempt状态/错误/未知用量保持；仅新增授权记录。成功重试不证明原请求未执行。
原材料、P04/P05输出和既有问题不改写；两处作者措辞弱化及体系归属需要独立人工复核。
