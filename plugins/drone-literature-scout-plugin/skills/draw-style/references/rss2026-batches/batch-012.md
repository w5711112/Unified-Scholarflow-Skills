# RSS 2026 优秀图语料：第 012 批（RSS2026_056–RSS2026_060）

> 状态：待用户确认，未冻结；以下结论尚未并入冻结语料。本批对用户明确关注颜色的 RSS2026_057、RSS2026_060 记录精确色号；RSS2026_056、058、059 只分析颜色与字体职责。

## RSS2026_056
<!-- rss2026-meta {"visible_figure_label":"Fig. 7","figure_track":"data/table","domain_tags":["LiDAR Odometry","RPE","Small Multiples","Lollipop Plot"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 010040.png。
- 定位信息：`Fig. 7: Comparison of LiDAR odometry performance across different algorithms based on RPE (m).`。
- 图的范式类别：2×6 small multiples 的对数菱形 lollipop/dot plot。
- **用户个人学习重点**：首次见到菱形承担数据图标记；菱形颜色、空心/环形状态多样，下面用直虚线连到底部，在一定程度上可替代柱状图。
- **补充核读**：所有主 marker 的几何基础都是菱形，差异主要来自颜色以及实心、空心、外环三种状态；caption 明确“外环包住菱形＝best，空心菱形＝second-best”。竖向点线是 lollipop stem，在对数轴上连到绘图区下界而不是零。

### 2. 图本身表达什么

六个场景 Bridge、Riverside、Roundabout、Town、DCC、KAIST 分列，两种 LiDAR OS2-128、VLP-16 分行，比较九种 ICP/系统算法的 RPE。每个小图内部用竖虚线分开 `ICP Variants` 与 `System`，y 轴为对数尺度，越低越好。

### 3. 逐元素与连接核读

**分面结构：**

- 上排 OS2-128、下排 VLP-16；六列场景共享同一列标题。
- 只有最左面板显示 y 刻度标签，其他面板保留网格，减少重复。
- 每个面板内部黑色竖虚线将左侧 ICP variants 与右侧 systems 分区。

**菱形 lollipop：**

- 彩色菱形的 y 位置编码 RPE，x 位置编码算法；同色竖点线从面板下界延伸到 marker。
- 点线不是误差棒，也不是从零开始的柱；在 log y 上只能表示“从可视下限到点”的位置锚定。
- 最佳结果为菱形外再套同色空心环；次佳为只画空心菱形；其余为实心菱形。
- 黑、蓝、青、绿、橙、黄、红、紫颜色在所有面板保持算法身份。

**图例与轴：**

- 顶部单行图例列出九种算法；使用同一菱形样例，不重复展示 rank 状态。
- 水平浅灰网格辅助读取 log 数量级；主刻度 `10^-1/10^-2` 或 `10^0/10^-1`。

### 4. 全局构图与阅读路径

读者先按列比较同一场景的两种 LiDAR，再按行观察同一硬件跨场景表现。每幅小图只保留稀疏点与 stem，因此 12 个面板仍不显成 12 组厚柱；rank 环/空心让最佳项在高密度分面中跳出。

### 5. 局部视觉语法

- 菱形比圆点更有方向感和面积辨识度；实心/空心/外环提供无需新色的等级通道。
- 点状 stem 与 marker 同色，但线宽远轻于 marker，避免被误读为柱体面积。
- 面板内部类别分界使用黑色长虚线，数据 stem 使用彩色点线，两类线型职责不同。

### 6. 为什么有效

它用位置而非面积承载数值，在 log 轴上比柱状图更诚实；菱形和 rank 状态让最佳/次佳无需额外文字。small multiples 固定硬件、场景和算法身份，读者能快速扫出跨条件稳定性。

### 7. 可以吸收的绘图知识

- **新增“菱形 lollipop”**：适合离散方法、稀疏类别、对数尺度或需要减少柱体墨水量的比较。
- `ax.vlines`/`stem` 只作位置导引，线从 y 轴显示下限而非伪造零基线；caption 应说明 log scale。
- `marker='D'`，最佳用 `markerfacecolor`＋更大的空心 `D` 外环，次佳只用 `markerfacecolor='none'`；颜色仍固定算法。
- 如果类别很多但只关心排名，可按值排序点图；若要强调绝对量或累积量，仍使用条形图。

### 8. 不足、误读风险与不应照搬

顶部九项图例很长；小面板无 x 标签，必须依赖全局图例和固定顺序；stem 容易被初看者当作误差棒；最佳外环与空心次佳在缩小后可能混淆。不能说每个菱形“形状都不同”，也不能把 stem 长度当线性差值。

### 9. 本图最值得学习什么（收录理由）

学习菱形 lollipop 作为柱图替代：颜色固定算法，实心/空心/外环固定普通、次佳、最佳，竖点线只辅助定位。

### 10. 证据边界

每个 RPE 的聚合方式、序列数量、误差/方差、失败值处理、面板下界选择、算法缺失点与所有场景正式定义未从截图确认。

## RSS2026_057
<!-- rss2026-meta {"visible_figure_label":"Fig. 5","figure_track":"data/table","domain_tags":["Behavior Cloning","Controller Gains","Heatmap","Small Multiples"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 010127.png。
- 定位信息：`Fig. 5: Behavior cloning prefers compliant and overdamped controller gains.`；论文为 *Tune to Learn: How Controller Gains Shape Robot Policy Learning*。
- 图的范式类别：主热力图＋六个共享语法 small-multiple 热力图。
- **用户个人学习重点**：经典热力图，重点关注红色配色、坐标系与字体样式。
- **补充核读**：大图 `(a)` 显示 7×8 增益网格并直接标成功率；右侧六图只保留色块、轴名和任务标题。Caption 定义深红＝更高成功率，成功区集中在左上 compliant、overdamped 区域。

### 2. 图本身表达什么

横轴 proportional gain `K_p` 从 32 到 2048，纵轴 derivative gain `K_d` 从 1 到 128。Bimanual Handover 主图的成功率最高约 0.50；六个其他任务/机器人设置也显示左上区域普遍更深，说明 behavior cloning 偏好低 `K_p`、高 `K_d` 的 compliant、overdamped gains。

### 3. 逐元素与连接核读

**主热力图：**

- 7 列×8 行，每格直接写 0.04–0.50 成功率；深格用白字，浅格用黑字，保持局部对比。
- 白色细分隔线让单元格清楚，但不形成重黑网格。
- x/y 刻度只写实际 gain 值，轴名使用 sans-serif 粗体数学下标。

**六个小图：**

- Dishrack Unloading、Dishwasher Opening、Dishrack Loading、三种 Block Stacking 条件组成 2×3。
- 省略数值和刻度文本，只保留二维格局；黑色轴线末端带简洁箭头，任务标题放在图下。
- 所有小图共享相同浅桃→深酒红色序列，但截图中没有独立 colorbar。

**色阶与字体：**

- 原生采样色可压缩为：`#FDE4D9 → #FBC6B1 → #FBAA8D → #FA8969 → #FA6C4C → #EF3E2E → #CF1C1E → #C0141A → #9C0C13 → #66000B`。
- 图内数字和坐标是现代 sans-serif，接近 Matplotlib 默认 DejaVu Sans/Arial/Helvetica 类；caption 另用论文 serif。仅从 PNG 不锁定单一字体文件。

### 4. 全局构图与阅读路径

左侧主图宽度和高度显著大于右侧小图，承担精确读数；右侧 2×3 承担跨任务模式验证。读者先理解主图坐标和值，再把同一读法迁移到六个无刻度小图。

### 5. 局部视觉语法

- 单色相顺序色只编码 success rate，不编码任务；任务由面板位置和标题承担。
- 低值使用非常浅的肉粉，高值过渡到近黑酒红，既有强动态范围又不引入彩虹色相跳变。
- 数字颜色按背景明度自适应；主图黑框略重，小图轴箭头简洁。

### 6. 为什么有效

红色顺序色符合“强/弱”连续量直觉，主图直接标数值保证精确，小图删掉重复信息保证整体紧凑。主大辅小的层级比七张等大热图更高效。

### 7. 可以吸收的绘图知识

- 主热力图用于教学坐标与精确值，small multiples 只比较模式；两者共享 `vmin/vmax` 和同一 colormap。
- 用感知上单调的浅粉→深酒红色阶，避免中段突然变亮；深浅阈值决定黑/白文字。
- Python 可用 `imshow`/`pcolormesh`，主图 `annotate` 每格，小图共享 `Normalize`；用 `GridSpec` 设置左大右小，不把七图等分。
- 若小图需要跨论文独立阅读，应补共享 colorbar；本图缺色条只能依赖 caption 的“darker red＝higher”。

### 8. 不足、误读风险与不应照搬

没有 colorbar，六个小图无法独立查值；主图黑外框偏重；小图没有 tick 值，必须依赖主图；如果各任务范围不同，共享色阶与否需明确。不能仅凭深色集中宣称统计显著性。

### 9. 本图最值得学习什么（收录理由）

重点学习“一个可精确读数的大热力图＋六个只看分布模式的小热力图”，以及浅桃到深酒红的连续色阶和深浅自适应文字。

### 10. 证据边界

各小图成功率数值、统一 `vmin/vmax` 的精确范围、每格 rollout 数、方差、统计显著性、字体文件和色图构造代码未从截图完整确认。

## RSS2026_058
<!-- rss2026-meta {"visible_figure_label":"Fig. 8","figure_track":"data/table","domain_tags":["Horizontal Bar","Zero-shot Evaluation","Rounded Bar","Uncertainty Interval"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 010312.png。
- 定位信息：`Fig. 8: Evaluation of CAP zero-shot on diverse embodiments`；论文为 *Contact-Anchored Policies: Contact Conditioning Creates Strong Robot Utility Models*。
- 图的范式类别：分组横向圆角条形图＋带端帽区间。
- **用户个人学习重点**：颜色一般；学习误差区间、字体形式、圆角和高占空比。以后类似条图尽量采用圆角，不喜欢直角；条本身要宽，组内留白小，让画面饱满。
- **补充核读**：上组 Internal 四条 83%、83%、79%、70%，下组 External 三条 88%、79%、72%。黑色水平区间带两端 cap，但 caption 没有定义是 SD、SE、CI 还是范围。

### 2. 图本身表达什么

同一 CAP checkpoint 在多种机器人与不同地点进行 zero-shot evaluation。Internal/External 是两组评估来源；Stretch、XArm、Franka、UR3e 用颜色区分。各条直接写成功率，并以区间展示某种不确定性或变动范围。

### 3. 逐元素与连接核读

**圆角条：**

- 七条均从 0% 起，四角圆弧半径一致，黑色细描边保证浅黄/浅紫边界。
- 条高明显大于组内间隙，组间留出一条更大空带；形成“组内紧、组间松”。
- 上组四条几乎铺满纵向空间，下组三条保持同样条高。

**区间与数字：**

- 黑色水平线穿过条顶附近，左右各有短竖 cap；它与条末端数值并非同一位置。
- `83%/79%...` 放在区间右侧或条外，使用大号 sans-serif 数字，不压进条内。
- 截图没有中心点 marker，条末端承担点估计的长度编码，区间线承担不确定性。

**轴与分组：**

- x 轴 0–100%，20% 间隔；只保留下轴浅灰线，无纵网格。
- `Internal/External` 竖排在左侧，通过大组间距而非框线分区。
- 底部图例用带黑边方形色块列出四种 embodiment。

### 4. 全局构图与阅读路径

横向条从左到右形成强方向，数字在右侧对齐近似列。高条宽＋小组内留白让数据区饱满；Internal/External 的大间距创造唯一的大节奏断点，避免每条都均匀散开。

### 5. 局部视觉语法

- 字体属于中性 neo-grotesk sans-serif，最接近 Matplotlib DejaVu Sans/Arial/Helvetica 一类；饱满的 `0` 来自较大字号、适中字重和宽椭圆字腔，不需要特殊“数字字体”。
- 圆角只改变条端的几何语气，不改变长度起止；圆弧半径应小于条高一半，避免胶囊过度可爱。
- 本图颜色普通，不录精确色号；保留黑色细轮廓有助于浅色条。

### 6. 为什么有效

圆角、厚条和紧凑间距让横向柱图不显骨感；大数字放在条外，区间线带端帽，读者能同时看点估计和范围。组内/组间两级间距比画粗分割线更柔和。

### 7. 可以吸收的绘图知识

- **新增“圆角条形＋高占空比”**：条宽大于组间留白；组内 gap 约为条高的 10%–25%，组间 gap 明显放大。
- Matplotlib 可用 `FancyBboxPatch(boxstyle='round,pad=0,rounding_size=...)` 代替 `barh` 的直角矩形，再用 `errorbar(..., fmt='none', capsize=...)` 叠区间。
- 圆角条形仍必须从统一基线起，不用圆端掩盖截断坐标。
- 大数字置于区间之外并预留右边界；小图中优先使用 tabular numerals 或统一数字宽度。

### 8. 不足、误读风险与不应照搬

区间统计含义和样本量未定义；部分区间非常宽；两条相同 83% 但区间不同，不能只读数字；颜色与 embodiment 的对应需查图例；外组 XArm/Franka 复用黄系，容易混淆。不能把区间称标准差。

### 9. 本图最值得学习什么（收录理由）

重点收录圆角、高占空比和“组内紧、组间松”的条形布局，以及带清楚端帽但不猜统计口径的区间画法。

### 10. 证据边界

区间类型、中心、样本量、每条 unique site 的具体位置、Internal/External 的划分规则、字体文件与圆角实现工具未从截图确认。

## RSS2026_059
<!-- rss2026-meta {"visible_figure_label":"Fig. 10 / Fig. 11","figure_track":"data/table","domain_tags":["Sim-to-real","Violin Plot","Failure Modes","Distractors"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 010350.png。
- 定位信息：左为 `Fig. 10: Left: Sim-to-real correlation... Right: Analysis of failure modes...`；右为 `Fig. 11: Relative success rate as a function of visual distractors...`。
- 图的范式类别：小提琴分布＋100% 堆叠条＋折线小提琴混合数据图。
- **用户个人学习重点**：“眼睛”形状有些花哨，只作参考；主要参考数字字体。
- **补充核读**：眼睛状几何是竖向 violin density，不只是装饰。Fig. 10 左把四个 EgoGym performance x 位置映射到 real performance 分布，Fig. 11 把每个 distractor 数量处的成功率下降分布叠在线上。

### 2. 图本身表达什么

Fig. 10 左显示 sim 性能与 real 性能正相关，四个 checkpoint 的分布中心接近灰色对角线；右侧 failure modes 的 success 比例从 CAP-A 的 20 增到 CAP-D 的 80。Fig. 11 比较五种模型随 distractor 数增加的相对成功率下降，CAP+Oracle 最稳，`π-0.5` 下降最大。

### 3. 逐元素与连接核读

**Fig. 10 左：**

- 四个紫色竖 violin 放在 x≈20/38/63/80，宽度编码 real performance 分布密度。
- violin 内有小菱形/短线式摘要，灰色对角虚线作为理想相关基线。
- 轴标题和数字使用细长 serif。

**Fig. 10 右：**

- CAP-A–D 四根 100% 堆叠条固定 failure categories 顺序；绿色 success 段直接写 20、37、63、80。
- 图例放在整幅左图下方，颜色承担 failure mode 身份。

**Fig. 11：**

- 五条彩线连接 distractor 数 0–4 的中心趋势；每个 x 位置叠同色竖 violin，形成“线＝趋势、眼睛＝分布”。
- 圆节点位于 violin 中心附近；紫、黑、蓝、红、橙各固定模型。
- y 轴以百分比显示 0% 至 −40%，横向浅网格辅助比较。

### 4. 全局构图与阅读路径

左块先回答 sim-to-real 与 failure composition，右块再回答视觉扰动鲁棒性。图9截图包含两个独立 figure/caption，而不是一个统一多面板；后续复用时应分别成图，避免把两个研究问题硬拼在同一画布。

### 5. 局部视觉语法

- 数字与轴标题接近 Computer Modern/Latin Modern/Times 风格的细 serif，`0` 窄而高；从 PNG 不能锁定单一字体文件。
- violin 透明填充、细轮廓和中心 marker 让分布可读，但在多色折线图中面积过多会显花。
- 100% 堆叠条内部大数字比在所有段写百分比更克制。

### 6. 为什么部分有效

分布形状能补充单一均值，尤其让 Fig. 11 看到 distractor 增加后方差变化；数字字体细而稳定，不抢数据。花哨感来自每个点都画 violin、颜色高饱和、线和形状重复叠加，信息密度接近过载。

### 7. 可以吸收的绘图知识

- 只有当分布宽度/多峰性是结论时才在折线节点叠 violin；若只需均值＋区间，改用 errorbar/ribbon。
- violin 可缩窄、降低 alpha，并让中心线/点比轮廓更强，避免“眼睛”抢主趋势。
- 数字可用 Latin Modern Roman/Computer Modern 类细 serif，但正式论文需保证轴字在最终尺寸可读。
- 独立 figure 的 caption 和图例不要在后期拼版中互相借用。

### 8. 不足、误读风险与不应照搬

Fig. 11 没有说明 violin 样本数和 KDE 带宽；彩色面积大；Fig. 10 failure legend 横跨底部且字号小；两个独立 figure 拼在截图中容易被误读成一个 3-panel 图。不能把 violin 顶底当置信区间。

### 9. 本图最值得学习什么（收录理由）

只适度保留“趋势线上叠局部分布”的可能性和细 serif 数字风格；眼睛状 violin 不作为默认节点装饰。

### 10. 证据边界

violin 样本来源、KDE 带宽、中心 marker 统计量、失败模式总 episode 数、Fig. 11 误差聚合和字体文件未从截图确认。

## RSS2026_060
<!-- rss2026-meta {"visible_figure_label":"Fig. 3","figure_track":"method/schematic","domain_tags":["Neuro-symbolic Policy","Iterative Learning","Process Diagram","Asymmetric Layout"]} -->

### 1. 截图身份

- 原文件：屏幕截图 2026-08-02 010544.png。
- 定位信息：`Fig. 3: Iterative Structure-Policy Co-Evolution.`；论文为 *Emergent Neural Automaton Policies: Learning Symbolic Structure from Visuomotor Trajectories*。
- 图的范式类别：非对称双区迭代训练流程图。
- **用户个人学习重点**：本轮重中之重，而且重要程度位于全部参考图的前列，按模板级基准处理。颜色、箭头、字体、排版、空间组织、形状丰富度都非常舒服；特别学习“不规则但流程清晰”的美，不把规整误当唯一好图，并核查竖虚线是否形成黄金分割。
- **补充核读**：Caption 定义左侧为用 learned encoder 聚类、增广 dataset，右侧为给定 dataset 下的 policy learning；残差网络从 PMM action prior 细化动作，并生成后续迭代的更新 encoder。形状差异与模块类型绑定，不是随意拼贴。

### 2. 图本身表达什么

训练在两条相互反馈的路线间交替：底部 trajectory 经 Vis/Pos Encoder、HDBSCAN 和 alphabet 形成第 `i` 轮 dataset；dataset 同时监督 RNN/PMM 结构模型与右侧 residual policy。右侧 Res. Net 结合 encoder feature、nearest symbolic state 和 PMM base action 得到修正动作，并将 learned encoder/cluster 信息反馈给下一轮 dataset。

### 3. 逐元素与连接核读

**左侧结构学习链：**

- 底部 `Trajectory` 用三张错位圆角卡表示序列，每张含 `a_t, I_t, p_t` 黄系 token；金色实箭头向上进入梯形 `Vis/Pos Enc.`。
- 小圆角标签 `Iter. i` 锚定编码器；绿色虚线继续向上进入 HDBSCAN 矩形，再到 `Alphabet i` 的四个符号色块 `c^0...c^3`。
- Alphabet 通过绿色虚线向右上转折，箭头指向顶部 `Dataset Iter. i` 的层叠圆角卡；这条虚线明确“下一轮/结构更新”，不是主数据实流。

**顶部 dataset 与结构模型：**

- Dataset 层叠卡以浅黄背板、乳白内板和四个 token `a_t, I_t, p_t, c_t^i` 构成；大小居中偏上，是左右两区的共享入口。
- 黑色实箭头从 Dataset 通过 `Loss Eq. (1)` 指向浅灰填充、深鲑边的 RNN 梯形；RNN 上方火焰表示可训练模块。
- 鲑色折线从 RNN 向下进入宽圆角 `Hypothesis PMM`，再沿右侧下行到 `a_base^t`，保持结构模型输出身份。

**右侧 policy learning 区：**

- 大型超浅绿圆角虚线容器占右下，内部以较小绿色虚线框表示 BC loss 输入 `I_t, p_t, q_t`。
- 中部梯形 `Vis/Pos Enc.` 配绿色火焰，输出 `f_t`；右下 `Res. Net` 也配火焰，接受 feature、`K-nearest` symbol 与 base action。
- 圆形加号节点把 residual 与 base action 合成 `ã_t`；黑色大弯箭头把 dataset action 引向最终动作，形成明显的跨区主脊梁。
- 绿色虚线从 BC/`c_t` 向上反馈到 Hypothesis PMM，两条上箭头并列；颜色与线型同时说明“policy/encoder 更新”。

**箭头职责：**

- 黑色实线：当前轮主要监督/动作数据流；金色实线：trajectory/image/position 数据流；绿色实线/虚线：encoder、residual 与迭代更新；鲑色实线：RNN/PMM/action prior 路径。
- 箭头绕开文字并在容器边缘折转；大弯线只出现一次，负责跨区主关系，其余连接短而贴近对象。

### 4. 全局构图与阅读路径

这不是等宽网格。右下大圆角框是最大视觉锚；左下层叠卡、左中梯形/矩形、左上小 alphabet 和上中 dataset 形成递进竖链；右上 RNN/PMM 与右下 policy 区形成第二条链。大框、小框、层叠卡与梯形错落排列，尺寸按语义重要性变化，形成**不规则但流程清晰**的非对称平衡。

竖灰虚线约在整张 PNG 宽度的 38.68%，按完整画布计算接近黄金分割 38.2%/61.8%；但上半图实际非白内容 bbox 为 x=247–1073，分割线在该活动边界内只有 29.66%/70.34%。因此“黄金分割感”可以作为构图候选与视觉解释，不能断言作者严格按黄金分割施工。

### 5. 局部视觉语法

**空间与形状：**

- 层叠圆角卡＝序列/dataset；梯形＝encoder/network transformation；普通矩形＝cluster/module；大圆角虚线容器＝policy 子系统；圆形加号＝融合。
- 同类对象复用形状，不同角色允许大小变化；不追求所有框等宽等高。
- 左链偏窄而纵向，右区偏宽而块状；不规则来自角色差异，而不是随机抖动。

**颜色及分布：**

- 黄系绑定 trajectory/dataset/观测 token：乳白 `#F7F0D3`、浅黄背板 `#F3E3AF`、金黄 token `#EFD98E`、深黄/ochre `#D0B63D`。
- 绿系绑定 clustering/encoder/residual/policy 更新：大区超浅绿约 `#EFF2E7`，浅绿模块 `#BECC9B`，深绿边/箭头 `#839F39`。
- 鲑红系绑定 RNN/PMM/base action：极浅粉 `#F9E7E1`、中浅鲑 `#DEAF9F`、深锈红 `#AE6242`；不是把红色平均撒到所有模块。
- 紫褐 `#9B7582` 固定离散符号 `c_t/c^0`，灰虚线只分区。冷暖两大体系由少量 mauve 桥接。

**字体：**

- `Dataset`、`HDBSCAN`、`Hypothesis PMM` 等标签与 Windows `Comic Sans MS` Regular 的 D/a/t/S/R/N 形态高度匹配；`RNN` 更接近 `Comic Sans MS Italic`。
- 由于截图是栅格，字体元数据不可读，`Comic Sans MS` 只作强匹配候选，不写成已从源文件证明的事实；若授权/跨平台需要，可用 Comic Neue 作为近似替代。
- 手写感只用于图内短标签和缩写，caption 仍使用正式论文 serif；这种“局部柔和、正文正式”的分工避免幼稚感。

### 6. 为什么有效

舒服感来自六个同时成立的条件：颜色按子系统聚类而非平均分布；形状按对象类型变化；尺寸按语义权重变化；箭头颜色和线型固定职责；短标签和缩写控制框内文字量；左窄竖链与右大系统形成非对称平衡。它证明规整不是目标，**可预测的阅读路径**才是目标。

### 7. 可以吸收的绘图知识

- **新增模板级母版“M9 非对称模块星座”**：它是全库最高优先级之一；复杂异构闭环图先判断是否适用。先确定最大语义锚，再围绕它放中小模块；大框、小框、层叠卡与梯形形成 3–4 个尺度，不使用一排同尺寸卡片。
- **黄金分割只作构图候选**：可先以 38/62 设画布分区，但必须再检查活动内容 bbox、箭头长度和视觉重量；不能把空白边距制造的比例当硬规则。
- 模块色按职责成片分布：黄＝数据/轨迹，绿＝可学习 policy/encoder，鲑＝结构模型/prior，灰＝分区；同一子系统内用浅填充＋深边/箭头。
- 字体可用 `Comic Sans MS`/Comic Neue 的短标签搭配论文正文 serif；网络名可 italic，数据/模块名 regular。长句禁止塞进手写框。
- SVG/PPT/TikZ 重绘时先搭大区和主脊梁，再布置短连接；折线统一圆角 join，箭头避开文字，虚线只表达迭代/反馈。

### 8. 不足、误读风险与不应照搬

若脱离 caption，火焰图标、`c_t`、PMM、K-nearest 和多种线色仍需图例/正文解释；字体识别不是源元数据结论；大弯黑箭头靠近左区边界，重绘时需防止压迫；配色较多，若角色不明确会迅速变杂。不能把“非对称”理解为任意错位，也不能为了形状丰富而给同类模块不同外形。

### 9. 本图最值得学习什么（收录理由）

本轮最高优先级：学习“非对称但有语义秩序”的模块星座——右侧大圆角系统、左侧层叠/梯形竖链、上方共享 dataset、职责固定的四色箭头，以及短手写标签共同消除机械框图感。

### 10. 证据边界

作者实际软件、原始字体文件、是否主动使用黄金分割、所有颜色源值/alpha、火焰图标正式含义、虚实线完整定义、PMM 与残差网络内部算法未从截图或公开源元数据完全确认。HEX 为 PNG 最终显示像素，不等于唯一可反推的源色。

## 本批综合

### 视觉家族

- RSS2026_056：对数尺度菱形 lollipop，rank 用实心/空心/外环。
- RSS2026_057：主大辅小的共享红色热力图组。
- RSS2026_058：圆角高占空比横条＋带端帽区间。
- RSS2026_059：小提琴分布叠趋势线与组成条。
- RSS2026_060：非对称模块星座式迭代流程图。

### 合并后的精华

- 056、058 都是柱状图替代路线：056 用位置＋stem 减墨，058 用厚圆角条增加饱满感；选择取决于是否强调数值位置还是实体占比。
- 057、059 说明分布/场需要层级：一个主图教读法，其余小图只做模式验证；若每个点都叠大 violin 会过载。
- 060 扩展 M3：系统流程不要求正交网格，允许由最大语义锚、异形模块和职责明确的弯箭头形成非对称平衡。
- 本批精确色板只收 057 的连续红阶和 060 的黄—绿—鲑—紫角色色；058 普通条色、059 多彩 violin 不进入偏好色板。

以上均保持待确认，不自动冻结。
