# RSS 2026 优秀图语料：第 006 批（RSS2026_026–RSS2026_030）

> 状态：待用户确认，未冻结；以下结论尚未并入稳定绘图规则。色号均为原截图像素中的代表值，不等于论文作者源代码中的原始色值；透明叠色会随底色改变。

## RSS2026_026
<!-- rss2026-meta {"visible_figure_label":"Fig. 7","figure_track":"data/table","domain_tags":["Control & Dynamics","Humanoids","Whole-body Control"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 001451.png。
- 定位信息：标题以 Fig. 7: Joint-level execution behavior 开头。
- 图的范式类别：论文多面板数据图（关节位置/速度均值＋一标准差＋局部放大）。
- **用户个人学习重点**：曲线看起来高级，主要因为浅灰、浅蓝、浅红背景带；要学习“框出局部再放大细节”的做法。图中黄点应学习其强调作用，但用户认为实际重绘时应换成别的颜色。
- **补充核读**：Caption 明确 solid lines indicate the mean over trials，shaded regions denote one standard deviation；因此浅色背景不是泛化的“标注差”，而是有定义的一标准差。

### 2. 图本身表达什么

(a) 比较双腿跳跃时 stance knee 与 swing abduction 的位置轨迹；(b) 比较双足站立时 wheel 与 knee 的速度轨迹。VBAC 生成的边界会诱发定性的 execution pattern change，而 Proposed 在两个任务中保持更一致的行为。图还比较不同离散时间参数 0.01/0.05。

### 3. 逐元素与连接核读

**(a) Joint position comparison in jumping motion：**

- 左上 y 轴 Stance Knee Pos. (rad)，x 为 Time (s)。Raw 黑、VBAC₀.₀₁ 蓝、Proposed₀.₀₁ 青绿、Proposed₀.₀₅ 红。
- 灰色水平虚线 qᵐᵃˣ 是位置限制。约 0.5–0.8 s 的源区用金色矩形框出，两条黑色虚线连接到右侧大放大窗；放大窗保持时间方向和颜色身份。
- 左下 y 轴 Swing Abd Pos. (rad)。Raw 黑线大幅超过 qᵐᵃˣ 后回落；三种受约束方法在上界附近保持较低幅度，均带同色标准差区域。

**(b) Joint velocity comparison in bipedal standing：**

- 右上 y 轴 Wheel Speed (rad/s)。Raw 黑、VBAC₀.₀₁ 蓝、Proposed₀.₀₁ 红；灰色水平虚线 q̇ᵐᵃˣ。
- 源框位于约 0.5–0.8 s，黑色虚线连接到右上放大窗；放大窗展示接近上限时红、蓝、黑曲线的局部振荡。
- 黑色文字 Constraint-induced Pattern Change (VBAC) 以两条实线指向 VBAC 的负向速度阶段和相关对比位置。
- 右下 y 轴 Knee Speed (rad/s)，同样有 q̇ᵐᵃˣ；黄点分别落在蓝线接近正上界和红线负向下冲的局部。
- 右上另有两个黄点标记 proposed 与 VBAC 在后段的不同状态。

**箭头/连线账本：**

- 源框 ↔ 放大窗｜两条黑色虚线连接｜无箭头头部｜局部对应。
- Constraint-induced Pattern Change 文本 → 曲线局部｜黑色实线/箭头｜说明 VBAC 的模式变化。
- 黄点没有文字引线；caption 未定义其正式含义，只能视为局部强调标记。
- 灰色 qᵐᵃˣ/q̇ᵐᵃˣ 虚线是约束参考，不表示方向。

**关系账本：**

- 左列共享跳跃任务，比较两个位置量；右列共享站立任务，比较两个速度量。
- 曲线颜色绑定控制器，浅带绑定同一曲线的一标准差；Raw 始终黑色。
- Caption 说明角标 0.01/0.05 代表 kinematic reasoning 的离散时间。

### 4. 全局构图与阅读路径

2×2 主图，左列位置、右列速度。最重要的高频局部直接嵌入主图空白处，不额外占一整行；面板下方的 (a)(b) 说明把两列分别收束为跳跃与站立。

### 5. 局部视觉语法

- VBAC 蓝 #004487；Proposed 红 #A40025；左列另一 Proposed 变体青绿 #44AA99；Raw 为深灰/黑。
- 代表性一标准差叠色：浅蓝灰 #B1D1D8、浅红灰 #C4A4AB、浅青 #91B0B7。
- 放大框金 #DDAA33；高亮点纯黄 #FFFF00；约束虚线中灰。
- 主均值线饱和、标准差带低饱和；放大窗与主图使用同色同方向，避免局部图失配。

### 6. 为什么有效

均值与标准差首先给整体趋势，局部放大再解释相位、振荡和模式变化；深线和浅带形成明确前后层级。源框—虚线—放大窗把细节对应关系说清，不需要读者猜测 inset 来自哪一段。

### 7. 可以吸收的绘图知识

- **强化并细化局部放大模式**：原位框选 → 两条细虚线 → 保持方向与颜色一致的放大窗；放大窗只保留要核对的线、带和约束。
- **强化统计线图模式**：均值用饱和深线，一标准差用同色浅带，约束用中性灰虚线。
- 高亮点不应与放大框共用同一鲜黄色。重绘时更稳妥的是白心深边圆点，或与金色框不同的深紫 #6A3877，并在图例/caption 定义。

### 8. 不足、误读风险与不应照搬

纯黄点 #FFFF00 过亮且与金色框竞争，含义又未定义；右列 inset 较大，遮住部分主数据；黑色注释跨越两面板附近，线端点需要仔细核对；曲线很多时浅带叠加会变脏。

### 9. 本图最值得学习什么（收录理由）

优先学习“深均值线＋同色一标准差带＋源框/虚线/放大窗”的高级曲线表达；黄点只保留“局部强调”思想，不照搬色值。

### 10. 证据边界

trial 数量、标准差计算单位、黄点正式含义、各 inset 的精确坐标范围、Raw 与各控制器的初始化完全一致性，以及统计显著性未从截图确认。

## RSS2026_027
<!-- rss2026-meta {"visible_figure_label":"Fig. 2","figure_track":"method/schematic","domain_tags":["Modeling and Optimization","Control & Dynamics","ADMM"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 001613.png。
- 定位信息：标题 Fig. 2: Overview of NRTO Framework。
- 图的范式类别：论文总图（双层迭代优化流程图）。
- **用户个人学习重点**：紫色＋阴影＋浅黄色的视觉效果不错，深紫与浅紫有对应；整体留白偏多。
- **补充核读**：颜色不仅装饰层级，还把“主步骤、内层 ADMM 容器、反馈回路、收敛判断”分成稳定语法；主流程与反馈使用不同线型。

### 2. 图本身表达什么

NRTO 是双层结构：外层 successive linearization 围绕当前 nominal trajectory 产生可处理的线性化问题；内层 ADMM 交替执行两个 block 更新与 dual update，直至内层收敛；随后更新 nominal trajectory，并由外层收敛判断决定输出控制参数或返回初始化/下一外层迭代。

### 3. 逐元素与连接核读

- 顶部浅黄框 Initialization (Outer iteration Iₒᵤₜ)，副行 Initial guess of nominal trajectory (x̂, û)。
- 下一浅黄框 Successive Linearization，副行说明线性化 dynamics f(x,u) 与 constraints around nominal trajectory。
- 中部浅紫大容器为内层 ADMM；顶部深紫条写 Inner ADMM Loop: Solve Tractable Linearized Problem。
- 容器内依次为 Block-1 update、Block-2 update、Dual update (Eq. 7c) for λ 三个浅黄步骤框。
- 右侧浅黄菱形 Is ADMM converged?；红叉支路返回 Block-1，绿勾支路向下离开内层。
- 下方浅黄框 Update nominal trajectory，随后菱形 Is Outer loop Converged?。
- 外层红叉通过右侧长紫色虚线反馈到最上方初始化/下一 outer iteration；绿勾向下进入 Output control parameters û, K。
- 关键变量组和更新公式字号较小；首个 block 的变量上标/波浪号未从截图可靠逐字符确认。

**箭头/连线账本：**

- Initialization → Successive Linearization → Inner ADMM Loop｜黑色实箭头，带紫色轻阴影｜主前向流程。
- Block-1 → Block-2 → Dual update → Is ADMM converged?｜黑色/紫色实箭头｜内层更新顺序。
- Is ADMM converged? 红叉 → Block-1｜紫色虚线反馈箭头｜内层继续迭代。
- Is ADMM converged? 绿勾 → Update nominal trajectory｜向下实/虚过渡箭头｜内层完成。
- Update nominal trajectory → Is Outer loop Converged?｜黑色实箭头｜外层判断。
- Outer loop 红叉 → Initialization｜右侧紫色长虚线箭头｜下一外层迭代。
- Outer loop 绿勾 → Output control parameters｜紫色向下箭头｜终止输出。

**关系账本：**

- 深紫标题条与浅紫容器共同定义 ADMM 的嵌套边界；浅黄步骤框表示可执行步骤/判断。
- 红叉与绿勾只补充“未收敛/已收敛”，真正方向由箭头给出。
- Caption 正式说明 outer successive linearization 与 inner ADMM 的双层关系。

### 4. 全局构图与阅读路径

单列自上而下主流程，右侧留出两条反馈通道；中部 ADMM 容器最宽，形成视觉中心。右侧长反馈需要留白，但下半部若干垂直间距仍可压缩。

### 5. 局部视觉语法

- 主步骤浅黄 #F8F4C7，次级浅黄 #EDE3B3 / #F1EAC0。
- 深紫 #6A3877 用于 ADMM 标题条与反馈强调；边框/阴影紫灰 #95718F、#9774A0。
- 内层容器浅紫近 #F1E8F1；红叉约 #A11425，绿勾为中深绿。
- 圆角矩形阴影统一向右下轻偏移；主箭头实线，反馈虚线。

### 6. 为什么有效

读者先看单列主链，再沿右侧虚线理解两个嵌套反馈；容器和标题条使 inner loop 不会与 outer loop 混淆。浅黄保持内容可读，深紫只压在循环边界和标题上。

### 7. 可以吸收的绘图知识

- **新增候选**：双层优化流程用“单列主链＋嵌套容器＋侧边反馈通道”，不要让反馈穿过步骤文字。
- 深紫 #6A3877、边框紫灰 #95718F 与浅黄 #F8F4C7 是可复用的论文流程配色；阴影统一且低强度。
- 前向实线、反馈虚线、收敛勾叉构成三重冗余编码，适合迭代算法。

### 8. 不足、误读风险与不应照搬

纵向留白偏多；局部变量/公式太小；紫色箭头阴影略重；红叉和绿勾未配文字，色盲场景需同时写 Yes/No；菱形中的大小写和换行不完全统一。

### 9. 本图最值得学习什么（收录理由）

学习深紫—浅紫—浅黄的层级关系、统一轻阴影，以及把内外两级反馈安排在侧边空白通道的做法。

### 10. 证据边界

Block-1/Block-2 变量的精确上标、nominal trajectory 更新式的逐字符形式、停止条件、迭代次数与箭头阴影是否由矢量源文件产生均未从截图确认。

## RSS2026_028
<!-- rss2026-meta {"visible_figure_label":"Fig. 3","figure_track":"data/table","domain_tags":["Modeling and Optimization","Control & Dynamics","GPU Computing"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 002008.png。
- 定位信息：标题以 Fig. 3. (a): Comparison of average solve-time scaling 开头。
- 图的范式类别：论文多面板数据图（log-log 多方法曲线＋3D scaling surface/散点）。
- **用户个人学习重点**：整体可参考内容不多；此前没见过右侧 solve time–horizon–variables 的 3D 表达。只记录“曲面上叠黑点”这种绘图方式，不学习其配色。
- **补充核读**：(a) 与 (b) 不是同一组数据的简单二维/三维复制；(a) 比较固定 10-link 任务的多 solver horizon scaling，(b) 展示 GPU-SLS 随 horizon 与 variables 的双变量 scaling。

### 2. 图本身表达什么

(a) 在 torque-constrained 10-link pendulum stabilization 上比较多种 NMPC solver 的 average solve time 随 horizon length 增长；GPU-SLS 在长 horizon 下更快。(b) 在一族 n-link pendulum 上，把 horizon、variables 与 solve time 的联合增长画成三维曲面并叠加观测点。

### 3. 逐元素与连接核读

**(a) 多 solver scaling：**

- x 轴 Horizon Length，y 轴 Solve Time (ms)，两轴均使用对数刻度，主要刻度约 10¹–10³ 与 10⁰–10⁵。
- 图例按 GPU-SLS、acados、Other 三组加粗标题组织；f32 蓝、f64 橙、HPIPM 绿、OSQP 红、primal-dual iLQR 紫、cparcon-IPM 棕、cparcon-ADMM 粉。
- 每条线在实际评测 horizon 处画圆点；不同 solver 的曲线终止位置不同。约 horizon=10³、time 数十 ms 附近有黑色 ×，截图未定义。

**(b) 3D scaling：**

- 三轴为 Horizon、Variables、Solve Time (ms)，可见刻度均为 10 的幂，属于 log 空间。
- 蓝色半透明网格曲面表示随两个自变量增长的整体 scaling surface；黑色散点表示离散观测/样本。
- 部分黑点位于曲面上方，保留了拟合/表面与观测偏差，而不是只给一张光滑曲面。

**箭头/连线账本：**

- 全图无方向箭头；折线连接实际 horizon 采样点，3D 网格线描述曲面，不表示流程。

**关系账本：**

- (a) 回答“不同 solver 随 horizon 怎样扩展”；(b) 回答“本方法同时随 horizon 与变量数怎样扩展”。
- Caption 为 (a) 给出 fixed 10-link task，为 (b) 给出 family of n-link pendulums；两图共享 solve time 指标但实验维度不同。

### 4. 全局构图与阅读路径

左侧图例独立占一列，中间 (a) 为主比较，右侧 (b) 为新颖三维补充。大号 (a)(b) 面板标签清晰，但图例面积较大。

### 5. 局部视觉语法

- (a) 主要沿用常见绘图库色板：蓝 #1E76B3、橙 #FE7E0D、绿 #2B9F2B、红 #D52627、紫 #9366BC、棕 #8B554A、粉 #E276C1。
- (b) 蓝色曲面在白底上的截图叠色约从 #5A8DAF 到 #75A8CB；黑点近 #000000。
- 网格细密且灰，三维曲面透明，让部分点和后方网格仍可见。

### 6. 为什么有效

单独曲面只能给平滑趋势，黑色原始点能显示数据支撑与偏差；两个自变量都跨度很大时，3D log surface 能在一张图中展示联合 scaling。

### 7. 可以吸收的绘图知识

- **新增候选**：当研究问题确实是两个连续/有序自变量对一个指标的联合影响时，可用半透明曲面＋高对比原始散点；必须同时保留轴名、单位和对数刻度。
- 曲面负责整体趋势，散点负责证据；若只画曲面，容易把拟合当成观测。
- 正式论文最好再提供 2D 切片或等高线，帮助精确比较；3D 不替代可读数的二维证据。

### 8. 不足、误读风险与不应照搬

透视遮挡、网格密度和单一蓝色使局部点难读；曲面拟合方法未定义；黑色 × 的含义不明；多方法图例过大。只学习“surface＋points”范式，不学习色板与布局。

### 9. 本图最值得学习什么（收录理由）

知道可把 solve time–horizon–variables 画成带原始黑点的三维 scaling surface，并明确它适用于双自变量联合趋势，而不是为了新奇强行立体化。

### 10. 证据边界

曲面计算/拟合方法、黑点样本数与聚合方式、黑色 × 的含义、各 solver 曲线终止原因、误差/重复次数和 3D 轴的精确范围均未从截图确认。

## RSS2026_029
<!-- rss2026-meta {"visible_figure_label":"Fig. 4","figure_track":"data/table","domain_tags":["Planning","Control & Dynamics","Safety","Robust Optimization"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 002027.png。
- 定位信息：标题以 Fig. 4. DeepReach rollouts 开头。
- 图的范式类别：论文空间数据图（同场景轨迹 rollouts、碰撞点与鲁棒管）。
- **用户个人学习重点**：喜欢 start–goal 之间的橙色曲线，视觉高级；右侧蓝色过渡带与橙色轨迹交相辉映。
- **补充核读**：右侧蓝带由图例正式定义为 Robust tubes，不是标准差、普通置信带或装饰背景；它与橙色 rollouts 的空间安全语义不同。

### 2. 图本身表达什么

在同一 Dubins car 障碍规避任务中，(a) DeepReach 的部分橙色 rollouts 在粉色圆形障碍附近发生碰撞；(b) GPU-SLS 的橙色 rollouts 全部位于蓝色 robust tubes 内并绕过障碍。Caption 声称 DeepReach 不能一致地 certify safety，而本文方法对全部 rollouts 认证安全。

### 3. 逐元素与连接核读

**共享场景：**

- x 轴 pₓ、y 轴 pᵧ，范围约 x=−0.75…1.0、y=−1.0…0.6。
- 黑色实心圆 Start 位于约 (−0.75, −0.75)；黑色星形 Goal 位于约 (1.0, 0.4)。
- 粉色半透明圆形 Obstacle 位于原点附近，半径约 0.3；浅灰网格与相同坐标范围跨两面板保持一致。

**(a) DeepReach rollouts：**

- 多条橙色半透明轨迹从 Start 出发，向右上弯曲到 Goal。
- 深红 × Crashes 聚集在障碍右下缘附近，约 (0.2, −0.2)。
- 轨迹透明叠加后中心区域更深，表现样本重合密度；线本身没有箭头头部，方向由 Start/Goal 标签定义。

**(b) GPU-SLS rollouts：**

- 橙色轨迹同样从 Start 到 Goal，整体位于蓝色 robust tubes 内。
- 蓝带由多层透明栅格/管状区域叠加，中心重叠更深、外缘逐层变浅；未见实际 crash ×。
- 图例保留 Obstacle、Crashes、GPU-SLS rollouts、Robust tubes 四项，便于与 (a) 对照。

**箭头/连线账本：**

- 全图无方向箭头。橙色轨迹是路径连接，方向只能由 Start → Goal 的文字锚定关系推断。

**关系账本：**

- 两面板共享起终点、障碍、坐标尺度与视角，唯一主要变化是规划/认证方法及其空间后果。
- (a) 的 red × 与 (b) 的 blue robust tubes 分别承担失败证据与安全包络证据。
- Caption 正式给出 adversarial and random disturbance 的背景，但截图不分别编码两种扰动。

### 4. 全局构图与阅读路径

左右同构对照，起终点和障碍固定。图例均放在右下数据较稀疏处；(b) 蓝管成为最大面积背景，橙色轨迹仍以高饱和细线浮在其上。

### 5. 局部视觉语法

- 主橙约 #FD7F0E；透明轨迹叠色约 #FE9A41、#FEAC64、#FECB9E。
- Robust tubes 由深浅蓝叠色组成，代表值约 #4F94C4、#71A7CE、#96BFDB、#B8D4E6。
- 障碍粉 #FEBFBF；碰撞深红 #8A0000；Start/Goal 黑。
- 蓝与橙既是互补色，又按“区域包络/中心轨迹”分工，不是两个方法的随意配色。

### 6. 为什么有效

固定场景使方法差异立即可见；蓝管提供“允许/认证区域”，橙线提供“实际 rollouts”，红 × 提供失败位置。区域、线和点三种视觉对象分别对应不同数据类型。

### 7. 可以吸收的绘图知识

- **新增候选**：路径规划数据图可用“浅色安全/鲁棒管＋高饱和中心轨迹＋离散碰撞点”，但每种对象必须对应真实数据语义。
- 同场景对照固定 Start、Goal、障碍、坐标和视角，只改变方法输出。
- 透明轨迹可通过重叠深度呈现样本密集区域，但不能冒充概率密度，除非正式定义。

### 8. 不足、误读风险与不应照搬

蓝管的栅格边缘略像低分辨率热图；图例在两面板重复；没有轨迹时间方向箭头；蓝管的构造方法与置信水平未给出；只看透视宽度不能推出概率。

### 9. 本图最值得学习什么（收录理由）

学习 #FD7F0E 橙色轨迹与 #4F94C4→#B8D4E6 蓝色鲁棒管的互补层级，以及“线＝实际轨迹、带＝安全包络、×＝碰撞”的空间数据语法。

### 10. 证据边界

rollout 数量、蓝管的数学构造与离散分辨率、两种扰动的分别作用、轨迹是否按时间均匀采样、碰撞判据和安全认证算法细节未从截图确认。

## RSS2026_030
<!-- rss2026-meta {"visible_figure_label":"Fig. 6","figure_track":"data/table","domain_tags":["Planning","Control & Dynamics","Safety","Robust Optimization"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 002047.png。
- 定位信息：标题 Fig. 6. Dubins car experiment。
- 图的范式类别：论文空间数据图（规划/执行轨迹＋鲁棒管＋密集障碍场）。
- **用户个人学习重点**：继续学习橙色虚线、蓝色背景/过渡带形成的高对比。
- **补充核读**：蓝色区域同样由图例定义为 Robust tubes；橙色虚线是 Planned Trajectory，蓝色实线是 Executed Trajectory，不能只把它们当装饰性前景和背景。

### 2. 图本身表达什么

GPU-SLS 在 20 m、30 个障碍物构成的密集约束场中规划一条橙色虚线路径；蓝色执行轨迹与规划轨迹高度贴合，并位于蓝色 robust tube 内，用于说明大规模轨迹优化与鲁棒约束满足。

### 3. 逐元素与连接核读

- x 轴 X Position，刻度 0–20；y 轴 Y Position，中心为 0，上下有约 ±1 附近刻度。
- Caption 明确有 30 个 obstacles；图内以半透明粉红圆表示，分布在轨迹上方和下方，未与轨迹直接相交。
- Executed Trajectory 为蓝色实线；Planned Trajectory 为橙色粗虚线；两者从 x=0 附近延伸到 x≈19.5。
- Robust tubes 为轨迹周围的浅蓝带，随路径弯曲并在局部变宽；多层透明度让中心较深、外缘较浅。
- 下方大图例分两行：Executed Trajectory、Robust tubes、Planned Trajectory。色块和线样很大。
- 灰色主网格较粗，横纵方向均贯穿数据区。

**箭头/连线账本：**

- 全图无箭头。轨迹方向由 x 从 0 到 20 的排列推断，图内没有 start/goal 标记。

**关系账本：**

- 橙色 planned 与蓝色 executed 共用同一坐标和时间/空间顺序；两者的偏差是主要比较对象。
- 蓝色 robust tube 是约束/认证区域，粉红圆是障碍；颜色和形状共同区分“允许区域”与“禁止区域”。
- Caption 提供 20 meters 和 30 obstacles，轴标题本身没有写单位。

### 4. 全局构图与阅读路径

单幅超宽低矮数据区突出长距离路径；大图例放在图下，caption 再放下方。数据主体简单，但图例占据的垂直面积接近主图，不够紧凑。

### 5. 局部视觉语法

- Planned 橙 #FE7E0D；Executed 蓝 #1E76B3。
- Robust tubes 的显示色约 #589AC6、#79AED1、#90BCD9、#ADCDE3。
- 障碍粉 #FEA5A5；网格灰约 #B0B0B0。
- 橙线使用长虚线，蓝线使用实线；即使转灰度仍能分辨 planned/executed。

### 6. 为什么有效

蓝/橙互补色与实/虚线形成双重编码；执行线、规划线和鲁棒管共轴叠加，读者无需在多个面板间对齐。粉红障碍用圆形区域而非点标记，直接显示空间占据。

### 7. 可以吸收的绘图知识

- **强化 029 的空间语法**：规划橙虚线＋执行蓝实线＋浅蓝鲁棒管，可在单图中同时回答计划、实际和安全裕度。
- 轨迹几乎重合时必须用线型区分，不能只依赖颜色。
- 鲁棒管应保持低饱和、低不透明度，让执行与规划线处于前景；障碍再用第三种低透明色域。

### 8. 不足、误读风险与不应照搬

图例过大、网格过重；轴标题无单位；没有 start/goal 或方向箭头；下方负 y 刻度的负号在截图中不够清楚，存在裁切/排版风险；蓝管含义虽由图例定义，但构造口径未说明。

### 9. 本图最值得学习什么（收录理由）

学习 #FE7E0D 橙虚线、#1E76B3 蓝实线与 #589AC6→#ADCDE3 浅蓝鲁棒管的前后层级，并保留线型作为灰度冗余。

### 10. 证据边界

障碍半径/坐标、robust tube 构造、规划与执行采样频率、坐标单位、轨迹误差指标、起终点和鲁棒约束的置信/集合定义未从截图确认。

## 本批综合

- 026 是统计线图与局部放大，027 是双层优化流程，028 是 scaling 数据与 3D surface，029–030 是空间轨迹与鲁棒管；四类视觉家族必须并列保留。
- 026 强化“深均值线＋同色一标准差＋源框—虚线—放大窗”；黄点只保留强调思想，建议改为白心深边或深紫。
- 027 提供深紫 #6A3877、紫灰 #95718F、浅黄 #F8F4C7 的流程图层级，以及实线前向/虚线反馈的嵌套循环语法。
- 028 只吸收“半透明 3D surface＋原始黑点＋三轴 log 刻度”；3D 必须回答双自变量联合趋势，并由二维切片补充精确读数。
- 029–030 共同形成稳定候选：橙色轨迹约 #FD7F0E / #FE7E0D，蓝色主线 #1E76B3 或 #004487，蓝色鲁棒管用 #4F94C4→#B8D4E6 的透明层级。带区是鲁棒集合，不是 SD/CI。
- 用户确认前，本批结论与色号只保存在分析卡和学习台账，不冻结、不写入稳定参考。
