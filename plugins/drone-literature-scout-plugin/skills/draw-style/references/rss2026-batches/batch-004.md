# RSS 2026 优秀图语料：第 004 批（RSS2026_016–RSS2026_020）

> 状态：已确认并冻结（2026-08-05）；已按适用场景将稳定规律并入绘图参考。

## RSS2026_016
<!-- rss2026-meta {"visible_figure_label":"Fig. 3","figure_track":"method/schematic","domain_tags":["Manipulation","Tactile Perception","Diffusion Policy"]} -->

### 1. 截图身份

- 原文件：`屏幕截图 2026-08-01 235532.png`。
- Caption：`Fig. 3: Overview of TouchGuide framework.`
- 图的范式类别：论文总图（训练模块、推理插入点与现实执行证据混合）。
- **用户个人学习重点**：学习 CPM 与 success/failure 的局部展开、模态图例的模块化表达，以及最右 2D/3D 分布图的对应。
- **补充核读**：顶部实际标记是 `V = Visual Observation`，不是 M；另有 `T = Tactile Observation`。蓝—红 2D 平面表示基础动作分布，蓝色 3D 曲面承担 CPM 的可行性评分/转向语义，二者不是同一张热力图的简单透视复制。

### 2. 图本身表达什么

`(a)` 训练 task-specific Contact Physical Model（CPM），把视觉/触觉观测嵌入与 noisy action 嵌入对齐；`(b)` 推理时把 CPM 作为外部模型插入基础策略的每一步采样/去噪，通过可行性分数梯度修正动作生成；`(c)` 在动作空间把这种修正解释为从 base distribution 向满足真实接触物理的 real distribution steering，并用成功/失败实物图验证结果。

### 3. 逐元素与连接核读

**顶部图例：**

- 橙框 `V`：Visual Observation；红框 `T`：Tactile Observation；紫色虚线框 `A_k`：Noisy Action。
- 绿色圆：Appropriate Action；红色圆：Inappropriate Action；金色星：Best Action。
- 浅蓝框 `ε_θ`：Predicted Noise；环形 `×K`：Denoising Steps；黄色层叠块：Base Policy；蓝—红渐变条：Action Distribution。

**(a) Contact Physical Model (CPM)：**

- 上支路：noisy action `A` 进入可训练的动作编码器 `E_A`（火焰符号），再经 `Norm` 得到 `a`，输入 `Contact Physical Contrastive Loss`。
- 下支路：tactile `T` 与 visual `V` 分别进入带雪花符号的冻结编码器 `E_T`、`E_V`，形成 `T^emb`、`V^emb`；`Concat` 后进入重复 `×N` 的 Transformer Encoder，内部明确画出 `Self-Attention` 与 `Feed Forward`。
- Transformer 输出 `O^emb`，经 `Norm & Projection` 得到 `O`，向上进入同一 contrastive loss；这构成 action 与 contact observation 的对齐训练。

**(b) If TouchGuide：**

- 右侧 base policy 的黄色层叠网络接收 `A_k` 与视觉/触觉条件，输出预测噪声 `ε_θ`；上下 `A_k`、`A_{k-1}` 和 `×K` 构成迭代去噪闭环。
- 左侧 CPM 接收状态/观测 `s`，提供动作可行性分数的梯度 `∇_A s`；黄色公式框 `η λ_k ∇_A s + ε_θ` 表示引导项与预测噪声结合后参与更新。截图不展开完整采样方程。
- 淡绿色容器和虚线连接把 CPM 从 `(a)` 的训练模块映射到 `(b)` 的推理插入点，而不是另起一条独立策略。

**(c) Toward Real Distribution Steering：**

- 左上实物图圆形放大窗叠加绿色/红色候选点与金色 best action；绿点通过 `Execute Action` 指向右上 `Success Case`，红点通过另一条执行线指向右下 `Failure Case`。
- 左下蓝—红 2D 分布平面标 `Sample from Base Distribution`，上方有若干红/绿圆与星形样本。
- 其下蓝色 3D 曲面标 `Steered by CPM`，曲面把“可行性随动作变化”转成空间高度；虚线把基础采样、CPM steering 和实物候选动作联系起来。

### 4. 全局构图与阅读路径

横向三段分别回答“CPM 怎么学”“推理时插在哪里”“它在真实动作空间产生什么后果”。顶部统一图例跨三段共享；左中使用网络流程，右侧换成分布小图与实物照片，使抽象机制落到可见接触结果。

### 5. 局部视觉语法

视觉、触觉、动作、成功/失败各自固定颜色和图形；训练/冻结用火焰/雪花而非额外文字。局部放大不是单一放大框，而是三层：模型结构放大、采样步骤放大、现实接触点放大。2D 色场适合表示概率密度，3D 曲面适合表示额外评分地形。

### 6. 为什么有效

图没有停在“CPM 模块接入 base policy”的框图层面，而是补齐了输入模态、梯度介入位置、动作分布变化与成功/失败结果，形成机制闭环。图例紧凑且可在三段复用。

### 7. 可以吸收的绘图知识

- 复杂模块应按“训练定义→推理插入→物理后果”分层放大，而非把所有细节塞进一个框。
- 模态/状态图例可采用带字母的微型圆角方框＋短文字；训练状态可用小图标补充，但全文必须统一。
- 同一变量的 probability distribution 与 feasibility score 不应强行画成同一种图：前者可用 2D 色场，后者可用 3D 高度面，再用样本点连接两者。

### 8. 不足、误读风险与不应照搬

中部去噪连线密集，若缩到 Obsidian 常规宽度会丢失箭头端点；右侧 3D 曲面无坐标轴和单位，只能作机制示意，不能读数。火焰/雪花等符号需配图例，不能依赖通用常识。

### 9. 本图最值得学习什么（收录理由）

学习“原理模块—算法插入点—分布转向—现实成功/失败”的多尺度证据链，以及用不同维度的图形分别表达概率与评分。

### 10. 证据边界

3D 曲面的具体轴、CPM score 数值、完整去噪更新式、候选动作点的采样数量与 success/failure 的统计代表性未从截图确认。

## RSS2026_017
<!-- rss2026-meta {"visible_figure_label":"Fig. 4","figure_track":"method/schematic","domain_tags":["Manipulation","Policy Distribution","Tactile Perception"]} -->

### 1. 截图身份

- 原文件：`屏幕截图 2026-08-01 235551.png`。
- Caption：`Fig. 4: Comparison of policy distributions in action space.`
- 图的范式类别：**概念性分布示意**，而不是带坐标与样本统计的正式数据密度图。
- **用户个人学习重点**：知道可用正态分布形状表达策略分布差异即可；整体不作为美观标杆。
- **补充核读**：四个子图讲的是“峰的位置与重合程度”，没有轴名、刻度、单位或数值，不能声称曲线来自真实拟合。

### 2. 图本身表达什么

`(a)` 视觉策略分布相对真实分布明显右移；`(b)` feature-level concatenation 产生的视觉—触觉策略仍与真实分布错位；`(c)` policy-level composition 将视觉、触觉策略组合后更接近真实分布；`(d)` TouchGuide 直接把偏移的 visual-only policy 向真实分布 steering，使 visual-tactile policy 与真实峰重合。

### 3. 逐元素与连接核读

- 四幅图均以浅灰横轴箭头和灰色竖向参考虚线为基底；灰色虚线钟形为 `Real Distribution`。
- `(a)` 蓝色实线 `Visual-only Policy` 峰值在真实分布右侧。
- `(b)` 蓝色虚线 visual-only 与紫色实线 `Visual-tactile Policy` 均在右侧，紫色略向真实峰靠近但仍未对齐。
- `(c)` 橙色虚线 `Tactile-only Policy` 位于真实峰左侧，蓝色虚线 visual-only 位于右侧，紫色 visual-tactile 的窄峰靠近真实分布。
- `(d)` 蓝色虚线仍在右侧，紫色宽峰与灰色真实分布大体重合；黑色弯箭头 `Steering` 从蓝色峰指向紫色/真实峰方向。
- 标题依次为 `(a) Visuomotor Policy`、`(b) Feature-level Concatenation`、`(c) Policy-level Composition`、`(d) TouchGuide`；TouchGuide 使用下划线斜体强调。

### 4. 全局构图与阅读路径

2×2 同构小图固定真实分布位置，只改变候选策略曲线；读者按 a→b→c→d 比较不同融合方式，最后一幅用箭头明确结论。

### 5. 局部视觉语法

灰色表示参照，蓝、橙、紫分别绑定视觉、触觉、视觉—触觉。虚实线同时区分角色，但线型规则在不同面板略有变化，主要依赖每幅图自己的图例。

### 6. 为什么有效

用峰位置和重叠程度代替长篇分布距离解释，适合讲“偏移—组合—对齐”。固定坐标骨架让唯一变化因素非常明显。

### 7. 可以吸收的绘图知识

- 需要解释 distribution shift/alignment 时，可用少量钟形曲线和固定参照峰构成同构对比。
- 这种图应明确标为 conceptual/schematic；若用于真实数据，必须补轴、归一化定义、估计方法和统计不确定性。

### 8. 不足、误读风险与不应照搬

图形一般，局部线型不完全统一，且高斯形状可能暗示未经验证的正态性。不能把示意曲线当成实验概率密度。

### 9. 本图最值得学习什么（收录理由）

仅收录“固定真实峰、移动策略峰、用弯箭头表达 steering”的极简概念范式，不收录其字体和整体外观。

### 10. 证据边界

曲线是否归一化、方差/均值、动作空间维度及其是否由数据拟合均未从截图确认。

## RSS2026_018
<!-- rss2026-meta {"visible_figure_label":"Fig. 5","figure_track":"data/table","domain_tags":["Manipulation","Policy Improvement","Simulation"]} -->

### 1. 截图身份

- 原文件：`屏幕截图 2026-08-01 235743.png`。
- Caption：`Fig. 5: Simulation success rates...`
- 图的范式类别：论文数据图（分组柱状图＋Average）。
- **用户个人学习重点**：学习柱顶置信表示这一顶刊基本操作；原图线太细，不照搬线宽。
- **补充核读**：Caption 明确 `Error bars show 95% finite-sample CI`，因此不是泛称误差棒，也不是标准差。

### 2. 图本身表达什么

图比较 `Raw Policy`、`Raw Policy + Inference-Time Steering`、`Raw Policy + Offline Improvement` 在 `Carrot on Plate`、`Eggplant in Basket`、`Spoon on Towel`、`Stack Blocks` 四个任务及 Average 上的成功率。Inference-Time Steering 在每组均最好；Offline Improvement 通常保留大部分提升，并在 Stack Blocks 上明显优于 raw policy。

### 3. 逐元素与连接核读

- 每组橙、紫、浅橙三柱；近似为：Carrot 65/71/67%，Eggplant 82/89/84%，Spoon 69/80/65%，Stack 34/46/59%，Average 63/72/69%。
- 所有柱顶均有黑色竖向 95% finite-sample CI 和短端帽；Stack Blocks 的区间较长，Average 的区间较短。
- 任务组与 Average 之间用竖向浅灰虚线分隔；y 轴为 `Success Rate`，0–100%，每 20% 一条浅灰水平网格。
- 图例横排置于底部，颜色块小且无边框；没有柱顶数值标签或显著性标记。
- 图中无箭头，阅读依赖同组并列与统一坐标。

### 4. 全局构图与阅读路径

四任务横向并列，Average 在虚线后独立收束；浅米白画布、低对比网格和下置图例让柱与 CI 成为主视觉。

### 5. 局部视觉语法

橙—紫—浅橙色相区分明确，柱边无重描；CI 使用黑线与端帽，但原图线宽相对柱宽偏细。纵向分隔线只承担语义分组，不延伸到 caption。

### 6. 为什么有效

读者能同时看到任务差异、平均表现和估计不确定性；Average 不混在普通任务中，避免被误认为第五个同类任务。

### 7. 可以吸收的绘图知识

- 顶刊柱图不能只给柱高；有重复/有限样本时应同时给定义清楚的 CI、SE 或 SD，并在 caption 写明口径。
- 误差线宽应在最终印刷尺寸仍可见，通常略细于柱边但显著粗于网格；端帽长度保持一致。
- 汇总指标与具体任务可用弱分隔线隔开，不需要额外大框。

### 8. 不足、误读风险与不应照搬

误差线与端帽偏细，缩放后易消失；无柱顶数值，精确比较需依赖坐标估读。CI 重叠与否不能直接替代显著性检验。

### 9. 本图最值得学习什么（收录理由）

学习“任务柱＋明确 95% finite-sample CI＋独立 Average”的基础规范，同时把可打印线宽作为质量门槛。

### 10. 证据边界

每个任务的试验数、CI 构造方法和方法间显著性检验未从截图确认。

## RSS2026_019
<!-- rss2026-meta {"visible_figure_label":"Fig. 2","figure_track":"mixed","domain_tags":["VLA Models","Manipulation","Long-Horizon Control"]} -->

### 1. 截图身份

- 原文件：`屏幕截图 2026-08-02 000013.png`。
- Caption：`Fig. 2: Performance Overview.`
- 图的范式类别：论文数据图＋极简知识点示意的混合总览。
- **用户个人学习重点**：学习 `+21%` 横向比较线，以及中、右区域用最小图形表达差异。
- **补充核读**：百分比括号的两个端点对应**基线柱顶到本方法柱顶**，而不是悬空的装饰标签；每个百分比必须绑定清楚的比较对象。

### 2. 图本身表达什么

`(a) Benchmark Performance` 展示 AR (Ours) 在 generalist 与 specialist benchmarks 上相对 OpenVLA、FM、ACT、DP 的定量表现；`(b) Execution Smoothness` 用两关节轨迹说明 AR 的动作更平滑、运动学更一致；`(c) Context-awareness` 用符号序列和真实任务图说明 AR 保留时间上下文，能完成 DP/FM 失败的长时程任务。

### 3. 逐元素与连接核读

**(a)：**

- 左小图图例 `SIMPLER` 橙、`Real` 绿，方法为 OpenVLA、FM、AR (Ours)。FM 到 AR 的两组柱顶分别以括号标 `+21%` 和 `+11%`，对应两种 benchmark 域。
- 右小图图例 `PushT` 橙、`ALOHA` 绿，方法为 ACT、DP、AR (Ours)；其中一组基线到 AR 的柱顶括号标 `+23%`。
- 括号由水平线和两端短竖线构成，文字放在线上方；只标最关键提升，没有遍历所有成对比较。

**(b)：**

- 三幅同构小图依次为 OpenVLA、FM、AR (Ours)；橙线 `Waist Joint`、绿线 `Shoulder Joint`。
- OpenVLA 与 FM 的轨迹包含较明显折点、回摆或平台；AR 的橙线为单一平滑起伏，绿线快速下降后稳定，图形用曲线形态而非统计数值说明 smoothness。

**(c)：**

- 左例以彩色 T 形块和状态/动作序列示意上下文组合；`DP` 下方配橙色叉，`AR (Ours)` 配绿色勾。
- 右例用两张机器人操作照片和顶部彩色 token/状态序列对比；`FM` 配红叉，`AR (Ours)` 配绿勾。
- 这些符号是简化任务状态和时序上下文，不从截图扩写其精确代数含义。

### 4. 全局构图与阅读路径

三块从定量性能、轨迹质量到长时程能力逐层扩展证据；每块内部都只保留一个比较结论，caption 再用 `(a)(b)(c)` 对应解释。

### 5. 局部视觉语法

橙/绿贯穿基准域与关节轨迹；红叉、绿勾提供直接结果语义。提升括号贴近柱顶，避免占用新的说明区。中右小图无重框，靠等宽排布和标题分区。

### 6. 为什么有效

它没有用一个巨型流程框讲所有优点，而是为三类主张各选最短证据：柱图、轨迹、同构成功/失败例。定量提升与定性机制互相补足。

### 7. 可以吸收的绘图知识

- 相对提升只标最重要的基线—本方法配对；括号端点锚定双方柱顶，百分比紧邻横线，并在 caption 说明相对/绝对提升口径。
- 总览图可把“数值结果＋轨迹形状＋极简任务结果”并置，而非强迫全部使用一种图表。
- 极简对比保持场景与对象同构，只改变方法及结果标记。

### 8. 不足、误读风险与不应照搬

小图没有 y 轴数值，`+21%` 等口径无法仅从截图判断是百分点还是相对百分比；中部平滑性没有量化指标；右侧彩色符号过小，必须依赖 caption。

### 9. 本图最值得学习什么（收录理由）

学习用成对柱顶括号突出单一核心提升，以及按主张类型选择最轻量证据图，不学习无刻度定量图的做法。

### 10. 证据边界

百分比计算口径、柱高统计量、轨迹时间轴/单位和顶部彩色序列的精确定义未从截图确认。

## RSS2026_020
<!-- rss2026-meta {"visible_figure_label":"Fig. 2","figure_track":"data/table","domain_tags":["Control and Dynamics","Modeling and Optimization","Robot Evaluation"]} -->

### 1. 截图身份

- 原文件：`屏幕截图 2026-08-02 000242.png`。
- Caption：`Fig. 2: Experiment results...`
- 图的范式类别：论文多面板数据图（参数热图、散点判定、多曲线收敛、逐轮热图）。
- **用户个人学习重点**：学习 `(a)(d)` 的具体热图、`(c)` 多曲线共轴，以及 half/非 half 的区分。
- **补充核读**：在 `(c)` 中 **half 用虚线、非 half 用实线**，方法身份由颜色区分；颜色与线型是两个正交编码通道。

### 2. 图本身表达什么

`(a)` 比较不同 Real synthetic distributions、学习率 η 和轮数 T 下，各方法相对 Monte Carlo 的 win rate；`(b)` 用 average wealth 与 average error improvement 展示方法相对 MC 的收益—误差权衡和 `H₀` 边界；`(c)` 展示多方法的 placing error estimate 随 T 收敛；`(d)` 展示各方法逐轮相对 MC 的 win rate。四图从参数网格、总体权衡、收敛过程、逐轮胜率共同验证方法。

### 3. 逐元素与连接核读

**(a) 参数网格热图：**

- 三行依次为 `Real_6 η`、`Real_20 η`、`Real_40 η`；六列为 `Full Kelly`、`Half Kelly`、`Sim_172`、`Sim_94`、`Sim_35`、`Sim_17_biased`。
- 每格小热图横轴 T 取 30、100、300，纵轴 η 取 0.1、1.0、3.0、10.0、50.0；右侧色条 `Win Rate (%)` 从红 0、黄 50 到绿 100。
- Full/Half Kelly 大多为绿色，仿真近似方法随 Real 分布和参数变化由绿转黄，`Sim_17_biased` 最偏黄橙。

**(b) 收益—误差散点：**

- x 轴 `Average Wealth`，y 轴 `Average Error Improvement vs MC (averaged across seeds)`。
- 黑色水平虚线为 `MC Baseline (Δ=0)`；红色 x=1 竖向点线为 `Wealth=1 (H₀ boundary)`，左侧淡红区标 `W<1: H₀ (no edge)`。
- 绿色菱形 Monte-Carlo 位于约 (1,0)；橙色方块为 Approx Kelly 的 Sim_17_biased、Sim_172、Sim_94、Sim_35；蓝色圆为 Ideal Kelly 的 `λ=0.5`、`λ=1.0`。点带可见误差线。

**(c) 多曲线收敛图：**

- x 轴 T 到 30，y 轴 `Placing Error Estimate (10 cm)`；所有曲线从约 0.3 衰减。
- Ideal Kelly 为粗黑点线，Ideal Kelly (Half) 为黑虚线，Monte Carlo 为棕色点划线。
- Sim_172/94/35/17_biased 分别用蓝/绿/橙/红；非 half 为实线，Half 为同色虚线。颜色锁定方法、线型锁定条件。
- 右侧嵌入机器人放置照片，以红/黄方框标两个目标区域；它解释误差的物理任务背景，不参与坐标读数。

**(d) 逐轮胜率热图：**

- 行为 `Ideal Kelly`、`MuJoCo Sim`、`Sim_172`、`Sim_94`、`Sim_35`、`Sim_17_biased`；列为 T=1…30。
- 右侧色条 `Win Rate vs MC (%)` 同样由红 0 到绿 100；各行色块随轮数改变，直接显示何时开始优于 MC。
- 左下灰色人形与坐标箭头是任务语境图标，不编码热图数据。

### 4. 全局构图与阅读路径

四面板 2×2 排列：上左参数全景，上右判定摘要，下左连续收敛，下右逐轮离散表现。`(a)` 信息密度最高，`(b)` 留白最大；不同图型通过一致的标签、绿色高值语义和 caption 串联。

### 5. 局部视觉语法

热图采用红—黄—绿发散式成功色带，数值方向由色条明确；散点用形状和颜色双编码方法家族；曲线用颜色和线型正交编码；照片/人形只提供物理语境。所有面板都有轴名或色条，避免“好看但不可读”的热力示意。

### 6. 为什么有效

同一结论经四种证据互相补足：参数鲁棒性、总体 trade-off、动态收敛和逐轮胜率。`half` 不占用新颜色，避免八条以上曲线失控；小热图阵列允许同时比较三个控制维度。

### 7. 可以吸收的绘图知识

- 多方法×多参数×多环境可用 small multiples 热图；每格共享轴范围和色条，行列标题承担条件索引。
- 多曲线图用颜色表示方法、线型表示同方法变体；主基线可再用线宽强化，但不同时改变过多视觉变量。
- 热图旁可配散点/曲线回答“为什么”和“随时间怎样”，而不是重复绘制同一数据。
- 颜色含义必须与色条一致；红绿对色觉缺陷不友好时应改为色觉安全连续色板并辅以数值或纹理。

### 8. 不足、误读风险与不应照搬

`(c)` 曲线很多、图例占据较大区域，缩放后同色虚实线可能难分；`(a)` 小格过多，在 Obsidian 常规宽度需要拆图或提供可放大原图。红—绿不应成为默认色板。

### 9. 本图最值得学习什么（收录理由）

学习为高维实验选择互补图型，以及用“颜色＝方法、线型＝half 设置、线宽＝主次”组织多曲线；同时学习带轴和色条的严谨 small-multiple 热图。

### 10. 证据边界

各点误差棒的统计量、热图 win rate 的试验数、`Half Kelly` 的完整定义和各仿真器名称对应关系未从截图外进一步确认。

## 本批综合

- 016：复杂方法图应补齐训练、推理插入、分布变化和现实结果四层证据；2D 分布与 3D 评分面分工表达。
- 017：钟形分布可用于概念性对齐示意，但必须与真实数据密度图明确区分。
- 018：柱图应给统计口径明确、终稿宽度可见的 CI/SE/SD。
- 019：关键提升用锚定双方柱顶的少量比较括号；不同主张选不同最小证据图。
- 020：高维实验通过 small multiples、散点、收敛曲线和逐轮热图形成互补证据；颜色与线型正交编码。

以上规律已分别写入方法总图、知识点示意与论文数据图稳定参考；论文标题仅保留为截图身份与定位信息，不作为绘图规律。
