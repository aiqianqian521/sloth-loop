# sloth-loop 本体：根本意义 · 方法论 · 使用教训 (2026-09-08)

> 本文件属 sloth-loop 本体(非任何具体项目)。记载 loop 的根本意义、工作哲学、以及使用 loop 时犯过的错与教训。下次用 sloth-loop 跑任何项目(不只量化)前先读。
> 触发: 用户校准"先将事情想明白才能做明白，遇到错误学会总结，这才是 sloth-loop。思想该存 sloth-loop 还是 PM"——想明白后定: 思想/方法论/教训归 sloth-loop 本体, 项目领域实例归该项目。

## 一、loop 的根本意义 (用户定, 高于 README"编排引擎")
loop 不是单纯"自动化跑回测/编排任务出指标"的工程工具。它根本意义是:

**把"分析一个对象(币种/项目/领域)"的完整认知流程，固化为可复用的东西，让同类对象不用重复输入、按同一流程走。**

```
A对象(首个) 分析训练若干周期
   └─ 总结: 什么错误、什么正确 (认知层对错, 非工程指标)
   └─ 沉淀: 把"分析→找对错→提炼规则"流程固化
        ▼
   可复用流程 (SOP骨架 + 偏差模式库 + 矫正规则库)
        ▼
B对象 / 其他同类对象
   └─ 遇同类问题 → 照同流程走, 不频繁手动输入
   └─ 只换"对象+周期"输入, 按既定流程自动跑
```

当前 PM(量化) = 对第一个对象(ETH)做分析训练, 把对错摸清楚 = 打可复用流程地基。地基打好, BTC/SOL 等其他币照走。

## 二、工作哲学: 先想明白才能做明白
动手前先把三件事想通:
1. 这事的根本目标是什么 (不是表面的"跑通/出指标", 是底层的"可复用流程+对错迁移")
2. 产出该放哪 (思想/方法论/通用骨架 → sloth-loop 本体; 领域内容/实例 → 具体项目)、为什么
3. 怎么才算"做完了" (不是"产出了报告", 是"沉淀了可复用流程+对错清单+可迁移规则")
没想明白就闷头跑 = 产出"一次性报告", 不服务于 loop 根本意义。

## 三、用 loop 犯过的错 (教训库, 持续追加)
- **错1 把 loop 当纯工程编排/架构评估器**: 闷头跑 wrapper 出胜率、做架构 gap 评估(PM-DEEP-DECOMPOSITION/PM-ARCH-EVAL/PM-FULL-AUDIT), 全是"针对一个对象的一次性深评估", 不是可复用流程。→ 教训: loop 产出必须含"可复用流程+对错总结", 不只是指标/报告。
- **错2 思想/方法论一股脑归到具体项目(PM)**: 把 loop 根本意义/SOP 存进 projects/pm, 换非量化项目就找不到。→ 教训: 通用方法论/哲学/使用教训归 sloth-loop 本体(本文件), 项目只存领域实例。
- **错3 脱离真实数据做抽象框架评估**: 全程没看价格走势就在搞"裁决4维退化/half-Kelly失效"等架构 gap, 回到走势才发现真正根因是"信号生成方向错(全逆势0顺势)"。→ 教训: 先看真实领域数据核"对错", 再谈架构矫正; 没看数据的评估是空中楼阁。
- **错4 自动不停跑, 用户无人可读进度+无可校验抓手**: 跑出一堆 md, 用户不知道到哪步、去哪看、怎么核。→ 教训: loop 产出必须含"人可读进度地图+可校验对账入口", 不只是机器产物。
- **错5 一直正向gap思维, 不反向从结果评估**: 一直"实现趋近设计找差距排批次", 没从"结果全年8单/3月连0单"反推系统根本不行。→ 教训: 定期从结果反推合格没, 不是只看实现差设计多少。

## 四、通用单项目分析 SOP 骨架 (从 PM 量化提炼, 适用任何领域)
输入: 对象 + 周期(如 币种+月份 / 项目+轮次)
步1 拉该对象该周期核心数据骨架(逐段/逐事件) + 整体定性(单边/震荡/突破...按领域)
步2 人视角标关键点/大机会 + 行情结构
步3 拉 AI/系统对该对象该周期生成的判断/标注逐条
步4 对账: 每条AI判断在真实数据什么位置 + AI判断 vs 真实 → 标对错
步5 找系统性偏差模式(AI偏向? 误判? 错过大机会?) → 命名偏差模式入"偏差模式库"
步6 沉淀"错误/正确"清单
步7 提炼可迁移规则(按对象类型各提炼)入"矫正规则库"
步8 归档: 对象实例(步1-6) + 偏差模式库(步5追加) + 矫正规则库(步7追加); 下个对象照SOP只换输入
固化: SOP骨架(本文件) + 项目实例(具体项目); 偏差模式库/矫正规则库按领域归项目, 跨领域通用部分回抽本文件

## 五、怎么用 loop (OODA) 落地这套
- Understand = 先想明白根本目标/放哪/怎么算完 (本文件哲学)
- Orient = 看现状(项目到哪/有什么数据/先看真实数据)
- Decide = 定可复用 SOP + task(config只换输入, wrapper自动步1-3出对账csv)
- Act = 跑(经 orchestrator, 禁手算领域数据)
- Verify = 对账核验(人标对错 + 看结果合格没)
- Learn = 遇错总结 → 追加"教训库"(本文件§3) + 偏差模式库/矫正规则库(项目)

## 六、关联
- 本文件 = sloth-loop 本体的思想/方法论/教训
- 项目实例(量化 PM) = projects/pm/PM-SINGLE-COIN-ANALYSIS-SOP-2026-09-08.md (量化特定8步+ETH 5月实例)
- 项目领域知识 = <KB_ROOT>/02_项目/<Q_PROJECT>/PM/
- README.md = sloth-loop"是什么"(编排引擎); 本文件 = "为什么这么用+哲学+教训"
- 下次用 sloth-loop 跑非量化项目: 先读本文件想明白, 复用§4 SOP骨架, 领域实例归该项目, 通用教训回抽本文件§3

## 错6 脱离设计文档本意把"多周期"当entry filter(2026-09-08 PM设计文档对错更正后追加)
- 现象: F1/B1/T1/S1/S2/S3 把"1d/4h斜率/HHHL/regime-MA熊段全禁BUY"当成entry过滤门跑了5连FAIL(L13 exhausted). 但11份PM设计文档逐句抽取实证: 0份把多周期当entry门, 全定位成场景标签/L2宏观背景/regime/指标验证维度/出场时间路由(见PM-DESIGN-DOC-CORRECTION-2026-09-08.md 二A).
- 规则6: 多周期/multi-TF只用作regime标签+EXIT出场路由, 禁作entry过滤门(任何"熊段全禁BUY"门系统性删reversal/底弹BUY赢单, 5连FAIL实证). 亏损变量在post-entry regime延续=EXIT层(DEEP-ROOT实证), 解在regime-conditional EXIT不在entry-gating.

## 错7 时间段写死成1d/4H/5min当死规矩(2026-09-08)
- 现象: 用户举例"查看1d/4h然后5min找入场点", 我硬把它当固定TF组合死规矩做单1d斜率门; 用户纠正"太呆板, 全动态时间都可验证".
- 规则7: 用户给的时间维度是举例非死规矩; 落地=timeframe grid/sweep全组合可验证, 不锁死selector. 设计里12:1聚合是机理(留), 1-3h/'15m,1h,4h'等固定阈值是默认可调(指标评估框架1.2已标"增窗口动态调整").

## 错8 空想架构方案不实证就给方案(2026-09-08 上一手PM-ARCH-PERSSIGNAL-MULTITF)
- 现象: 上一手不读源码不实证就说"启用detect_trend_4h当entry filter"是正解; DEEP-ROOT实证它实为labeler(只赋trend_state当标签不接return过滤), 与我"启用当filter"臆测矛盾.
- 规则8: 架构方案须先实证(走段+5min核+读源码)再给; 禁"已判据不实证就给方案"(=错3的延伸). loop本体: 先看真实领域数据核对错, 再谈架构矫正.

## 错9 凭上下文印象判断现状而非读文件核对(2026-09-08 本会话暴露)
- 现象: 本会话开口即把"PM流程已偏离既定"当事实要"修复", 用户也判我"上下文严重幻觉". 实际读NEXT/WAKEUP/PM-LESSONS/DEEP-ROOT后真相相反: 全程走sloth-loop编排(md5一致), 设计文档本意(regime+EXIT)正确, 是我之前偏离entry-filter后实证自回正. 我把"自己偏离后的失败"误读成"设计流程失败".
- 规则9: 唤醒/接手必先读真实文件锚(WAKEUP/NEXT/PM-LESSONS/相关产出)核现状, 禁凭上下文印象/会话残留判断"流程状态". 印象判断!=读文件核(=ooda Observe硬门). 幻觉来源=把自身偏离失败误归因到设计流程.
- 链接: 错3(脱离真实数据做抽象评估)/错8(空想方案不实证)的元层; 本次是"连'现状是否偏离'都没读文件就下判断".

## 错10 拆解停在月级太粗, 须下沉到人可读最细 digest 粒度(2026-09-09 PM A层暴露)
- 现象: 把"月度行情判断"做成一个月单标签(单边涨/跌/突破夹震荡…)就交差, 用户纠正"不应该是整月的笼统标记, 而是详细标记月份的某一天, 价格从xx到xxx"。= 违反§一"完整→无限拆解N子项各实现再组合", 停在月级=拆解不够细; 也违反错4(人可读可校验抓手)。
- 规则10(通用拆解粒度): 认知流程的"整体定性"须下沉到**人可读可校验的最细可digest粒度**(日级/子段级带价格从到), 编排产物含逐单位价格叙事供人核验, 不停留在笼统期级标签。期级/月级标签只能是从更细粒度读出的 digest, 不能是唯一产出。与错4(人可读进度)/错9(读文件核)同源: 给人留可校验的最细抓手。
- 项目实例: PM-LESSONS L15(A1日级详细标记) + pm-regime-diag-A-daily 任务。

## 错11 把大周期regime的"滞后"当成可消除的坑, 误提"换净涨跌regime去滞后"(2026-09-09 B1后用户点破)
- 现象: B1 的 tw_dir=结构状态机(HH/HL/LH/LL)滞后标签, 与窗内净涨跌方向不一致(如 4h DOWN 1894->2072 标DOWN; 1d UP 4759->3386 暴跌却标UP WEAK)。我把它框成"认知坑"并给用户列选项B"换净涨跌regime"去滞后。用户纠正: **当行情形成时是由很多个5min构成1h, 大时间天生在行情启动之后才能捕获到; 滞后不是bug而是多周期机理的必然**; 震荡磐肯定不是一开始就形成, 而是经过多个时间周期判断后才形成的震荡。即"滞后"是本质属性, 不可消除也不该去消除。
- 规则11(多周期分工原理, 治本): **大周期(1d/4h/1h)regime=滞后已形成的"上下文+EXIT路由"用**(趋势->trailing TP宽停 / 震荡->固%分层fade / 突破->trailing ride), **绝不用于'抓启动'**; **启动发生在5min层**, entry必须信号来时实时决策(不能再等1d确认, 那时行情已走半截)。**震荡磐late-confirm是定义使然**(单bar不能叫震荡, 须来回>=3且时长>=2h累积), 价值不在"尽早识别震荡"而在 ①已确认震荡内做什么(fade分层) ②震荡->突破的过渡(B4, 这个是相对更早可抓的"启动"层)。**任何"让大周期regime更早/不滞后"的方案=伪需求, 退候选**(含我上轮的"换净涨跌regime"=错)。
- 链接(这是更高维的根因): 直接解释 错6(多周期regime当entry filter)/错8(空想方案不实证)/**L13 entry-gate 5连FAIL** 的理论根因——**滞后label用在了需要及时性的entry层**, 所以5连(B1 rsi-band/T1 slope/S1 HHHL-sym/S2 HHHL-asym/S3 regime-MA)同灭: 不是阈值/机制错, 是用错了层。正解=滞后label转EXIT路由(**F5 regime-conditional trailing TP**, 趋势段让利润奔跑非被1.8%封顶) + 启动用5min实时决策; 与NEXT已立 **B4过渡/F5路由** 路线完全一致, 二者正是"滞后label用于路由、启动用于实时入场"的落地。
- 元: = 错3(脱离真实数据空想)/错8(空想方案)在"时间机理层"的延伸——不先想明白"多周期=5min构成大周期必然滞后"就给方案; 解=先想明白时间机理再谈架构矫正。实证锚: 2026-02 大跌, 5min/4h 自 02-03 08:00(2357->2219)已动, 而 1d 窗要到 02-08 才标出下跌确认——1d"确认"晚于行情启动即此机理。

## 错12 把错11过度修正成"大周期完全离场entry", 漏了"事后历史上下文软调和"角色(2026-09-09 用户二度点破)
- 现象: 错11写"大周期regime绝不用于抓启动"对(抓启动=抓时机, 大周期因5min构成而滞后不可为), 但我没点出大周期在entry层的"软角色", 易被读成"大周期完全不碰entry"。用户纠正: 大行情判断的真正用法= **5min信号触发后, 用已形成的历史大周期对当前信号做事后判断**(非抓启动、也非EXIT路由独占), 例: 5min涨+1h涨出现逆势(SELL)信号→过滤; 用户自评"有点极端, 再理解"。
- 规则12(大周期entry软角色=事后历史逆势调和, 非硬门非离场): 5min先行触发(entry=抓启动层, 错11对), 触发瞬间用 **已确认的历史大周期regime**(滞后但已形成、对当下已不算滞后)做 **软调和**: 逆势 → **降置信 x0.8 + needs_human + 出场路由收紧**(counter-trend用更紧TP/快停trailing), **不硬阻断**。理由: 硬阻逆势=L13五连FAIL复演——系统性杀掉ETH均值回归的反弹边缘盈利单(实证锚 2025-11-09 19:45 BUY RSI74 +1.275 TP3 = 逆势-macro-DOWN赢家, 被F1macro硬门抑制, F1净亏-12.35弃)。零逆势感知亦失(实证锚 5/29->6/6 fade顶抄底、+1.275空单被1.8%封顶错过26%趋势)。两端皆失, 正解=软调和。
- 链接已有decomp: C2(regime=label非entry阻断, 路由EXIT+降置信x0.8+needs_human)本就是此软角色的既定落地; 非新规则, 是点明错11边界。错11+错12合=大周期在entry的完整角色: 不可抓启动(错11), 可事后软调和(错12, 不硬门)。
- 验证锚(供C2落地双满足): 6亏月双案例——5/29抄底该被逆势awareness降置信/过滤(零感知F), 2025-11-09反弹赢家该被软调和保住非硬门杀(硬门F); C1不一致枚举 -> C2软调和 -> 两锚同时pass才算对。

## 错13(认知补全) 把"逆势/顺势"当二元、以为TF趋势就够判 —— 漏了 reversal vs continuation 需多维度分类(2026-09-09 用户三度点破, 锚 2025-11-09 19:45 BUY +1.275)
- 现象: 错11/12聚焦"大周期逆势硬过滤杀赢家"; 用户再点破: 触发时大周期(1h/4h)若都处上升, 5m信号就不再是简单逆势, 而是 reversal 还是 continuation(顺势) 之分; TF趋势给不出这个判据, 须其他维度。
- 实例锚(2025-11-09 19:45 BUY 3427.65 +1.275): 4h-LIVE=UP(04:00 O3374->C3420 +1.4% HH+HL); 1h completed=LH+LL(DOWN) 但 forming 11:00-11:45 O3400.5->C3426.85 已翻上 -> 大周期语境=上升。在此上升语境, 5m BUY 疑: 反转(对3380小回调反弹) OR 顺势(4h上升中回踩延续)。detector 标 allow_reversal 但其自身 上升趋势/strong/fib56.47%/RSI74(非超卖追强)/位置just below前高3434 -> 多维综合更像 **pullback-continuation**, 非典型reversal。
- 规则13(TF趋势只给上下文不给 reversal/continuation 判据; 多维分类 -> 路由 EXIT, 非entry阻断): 5m信号触发后, 用多维度综合判该信号 reversal vs continuation: ①多周期共振(forming+completed; 此单30m/1h-form/4h三同向上) ②回撤深度fib(<50%浅=continuation pullback / >61.8%深且破结构=reversal; 此单56%深但在强势里=continuation) ③RSI动量(continuation买强50-70升/reversal买超卖<30; 此单74=追强continuation) ④detector自身趋势/层级标签(此单标上升strong, 与reversal标张力) ⑤位置vs前高前低(此单just below前高3434=突破延续)。分类结果 -> 路由EXIT: reversal -> 分级fade TP(固%); continuation -> trailing TP让利润跑。此单被标reversal -> 固定TP3封顶+1.8%=+1.275, 错失实跑+6.7%(漏+4.9%) = 错的就是分类(continuation误标reversal)->EXIT封顶 = F5根因之一。
- 链接: 承接错11(大周期滞后)/错12(软调和非硬门); 把"entry过滤"问题升级为"reversal/continuation分类->EXIT路由"问题(分类决定EXIT而非entry)。错11+12+13合 = 大周期在决策的完整角色: 上下文(11) -> 逆势软调和(12) -> reversal/continuation 多维分类路由EXIT(13)。落地 = 多维 rev/cont 分类器 + F5 regime-conditional trailing(continuation趋势段trailing / 反弹段分级)。



## 错14(认知补全) reversal/continuation 二元仍太粗 —— 反弹(HTF刚启动上涨)是第三态, 须独立分类与评估(2026-09-09 用户四度点破)
- 现象: 错13把大周期上升语境下5m信号分成 reversal/continuation 二态; 用户再点破: 大周期"上升"本身按**相位**裂成两类 —— ①已成立的上升(走出HH/HL、多根确认、是已成立趋势里的一次回踩)=顺势 continuation; ②刚启动的上升(前一根大级别刚从下跌翻上、未确认新高、move 是 fresh launch)=反弹 rebound。反弹≠顺势≠逆势抄底, 它是自己的第三场景: 可能续成新趋势、也可能掉回去, 须单独综合评估。
- 实例锚(2025-11-09 19:45 BUY 3427.65 +1.275): 错13先前判 pullback-continuation; 按错14再加 HTF 相位维度 —— 4h LIVE=UP 但 1h completed 仍 = LH+LL(DOWN)、仅 forming 翻上 → 1h 上升是"刚启动"(未确认 HH/HL)=**rebound**, 非已成立 continuation。它后续续涨 +6.7%(rebound 续成趋势) → 固定 TP3 封顶 +1.8%=+1.275 是双重错(既漏顺势、也漏反弹续涨)。
- 规则14(三态分类, 反弹独立成类, 第6维=HTF move maturity/phase): 5m 信号触发后按**六维**判 reversal / continuation / rebound 三态: 错13 五维(①多周期共振 ②回撤深度fib ③RSI动量 ④detector趋势标签 ⑤位置vs前高前低) + **第6维 HTF行情相位**(完成根是否已出 HH/HL 确认 vs 仅 forming 翻上刚启动; 已确认=continuation / 刚启动未确认=rebound / 大周期下跌中=reversal)。三态路由 EXIT: continuation→trailing TP 让利润跑; rebound→两段式(先紧保本 trailing 防掉回, rebound 确认续涨[出HTF新HH]再放宽 trailing); reversal→分级 fade TP 或软调和(错12)。反弹独立成类的理由: 它的 EXIT 既不能照 continuation 一上来就宽放(可能掉回), 也不能照 reversal 封顶(可能续成趋势), 须"先保后放"两段式。
- 链接: 承接错13(rev/cont 二元→EXIT路由); 错14 把二元升三态(reb 独立), 第6维=HTF 相位。错11+12+13+14 合 = 大周期在决策的完整角色链: 上下文(11)→逆势软调和(12)→rev/cont 二分(13)→反弹补第三态(14)。落地 = 多维 rev/cont/rebound 三态分类器(6维, 第6维 HTF 相位) + F5 regime-conditional EXIT(continuation trailing / rebound 两段式先保后放 / reversal 分级)。
- 约束(守错6/L13): 三态是 label 决定 EXIT 路由, **不阻断 entry**; 趋势/震荡/反弹月的差异在 EXIT 不在 entry。EXIT 路由属 C/D 层, 须用户拍板后实施; 三态分类(label)属 B 层诊断可自动推进但归档后给用户校验。


## 错15 "让利润奔跑"≠日内紧ATR trailing(2026-09-10 F5-simple双sim实证FAIL, 弃)
- 现象: F5候选把固定TP3(+1.8%封顶)换成"TP2后2xATR 5min紧trailing(breakeven底线)", 期望让rebound续涨/continuation赢家跑过封顶. 全期双sim实证 diff_total=-8.1(负=弃): 锚2025-11-09 +1.275->+0.9095(更早更低位TRAIL_EXIT), RCR三态全变差(cont-2.30/reb-4.86/rev-0.48/mixed-0.47), 赢月Top5全削, f5凭空多3亏月(9 vs 6); 仅3输月救+1.07(2026-02+1.04/2026-05+0.44/2025-10+0.03).
- 规则15: "让利润奔跑"不可用日内紧ATR trail——2xATR(5min≈15点)被TP2后正常回撤震出, 兑现反<固定TP3且错过后续延伸. 让赢家跑须: trail建在更高TF(4h结构底)或更宽(>=4xATR 1h)或阈值激活(达+3%才开trail), 使日内5min回撤不把趋势单震出. 且纯统一trail净负(输月救+1.07但赢月削更多)->须类条件(仅cont/rebound-extends trail; reversal/mixed仍封顶fade). BASE2复现+38.1076核单变量有效.
- 链接: 错14(rebound续涨需trailing)方向对但F5-simple机制错; 错15=trailing的TF/宽度/激活机制. 与错11(大周期滞后用于EXIT路由非抓启动)合: trailing时间框架须匹配持仓周期(日内5min回撤不该出4h趋势单). 实证锚: 2025-11-09锚更早离场miss+6.7%.
- 弃(F5-simple不入矫正规则库, 守§0.1.4/错8 实证). 下一步F5b=宽/HTF trail+类条件, 待用户拍板C/D层.

## 错16(实测clincher, refine错12) 入场签名分离方向反向——逆势抄底=ETH edge(49%利润), 顺势反弹esp+rsi接刀=亏损主源; separable=0=门方向错非分不开(2026-09-10 pm-entry-trace)
- 现象: 错12预设"顺势反弹应更好"做separable门; pm-entry-trace 4/5 PASS唯separable=0. 核验macro4h与wrapper规则0不一致(分组可信). 实测反转假设: G2逆势反弹 n=25 WR0.76 +17.65 ≫ G1顺势反弹 n=31 WR0.355 +0.10(25SL近零废单). 逆势抄底flag n=27 WR0.74 +18.58=BASE2全+38.1的49%=ETH结构性edge. 最坏桶顺势+rsi接刀 n=19 WR0.26 -1.85; 最好逆势+rsi接刀False n=6 WR0.83.
- 6亏月4个(2024-01/2025-01/2026-02/2026-05)被G1顺势反弹主导(14/33单), G2逆势反弹仅3 → 用户"为何5月亏/为何不开空"=亏在顺势反弹弱入场(RSI接刀追极值)非逆势. 5连FAIL机制闭环: 硬门杀逆势抄底49%引擎+留顺势废单. 锤实错6/L13.
- G2逆势反弹6罕见输家=5/6 rsi接刀=True的逆势SELL(4h上涨做空接刀, RSI超卖仍逆势空); BUY逆势抄底(4h下跌抄底)≈全赢 → 逆势SELL+RSI超卖接刀是逆势抄底内小亏源, 出场/微调方向非硬门.
- 规则16: (1)ETH edge=逆势抄底早反转捕捉, 不可硬门阻(=错6/L13复演); (2)顺势反弹esp+rsi接刀=亏损主源, 但entry-rule砍它收益微小(pencil剔19单仅+1.85), 优化重心在EXIT侧F5b(让逆势反弹跑)+逆势SELL接刀微调, 非砍顺势废话; (3)separable按真方向(逆势>顺势)但不靠翻转门硬过=诚实记录reverse-separable(守错8); (4)错12 refine: 软调和不杀逆势抄底(原"保顺势赢家"muddled, 顺势反弹非赢家).
- 链接: 错6/L13->本节机制闭环; 错12->本节refine定向; 错14(rebound第三态)->逆势反弹属rebound子集=edge; 错15->EXIT侧F5b待拍板. 候选A/B/C=C/D层须用户拍板+5min证非自跑. 证据PM-ENTRY-TRACE-RESULT-2026-09-10.md md5=458C550D.

## 错17(更正错16过度推广 + 对称edge; 错9强化) 逆势SELL+RSI接刀=赢家非亏源; ETH edge=逆势+RSI极值两向fade; 顺势续涨/续跌追势=弱(2026-09-10 SELL侧细化)
- 现象: 错16只看G2逆势反弹6输家(5/6逆势SELL接刀)就判"逆势SELL+RSI超卖接刀是小亏源". SELL侧全量细化纠正: 逆势空+RSI接刀(4h_UP SELL+RSI超卖) n=13 WR0.62 +6.18=赢家(8赢5输); 逆势空+非接刀 n=9 WR0.33才弱. 顺势空(4h_DOWN SELL) n=18 WR0.39 SL0.83=弱(趋势空反而差).
- 对称edge(入场两侧): edge=逆势+RSI极值两向fade[BUY 4h_DOWN买+RSI低 WR0.65+10.23 / rebound/rebound BUY WR0.68+15.41; SELL 4h_UP空+RSI超卖 WR0.62+6.18 / rebound/rebound SELL WR0.52+9.36]=早反转/均值回归; 弱=顺势续涨/续跌追势[BUY回踩型1h_reb/4h_cont WR0.30 / SELL顺势空4h_DOWN WR0.39 SL0.83]=追势. 机制=signal_detector本质RSI极值均值回归, 逆势fade赢顺势chase弱.
- 规则17(对称入场签名+勿从输家过化): (1)edge=逆势+RSI极值两向抄底/接刀不可硬门阻(=错6/L13); 弱=顺势续涨/续跌追势软调和不硬阻(守错12); (2)勿从某标签输家子集过化推广该标签好坏=错9的统计版, 必须全量分桶核WR/pnl再判(此次G2 6输家不等于逆势SELL接刀整体); (3)5连FAIL终极锤: 要求顺势macro门=杀逆势fade edge+留顺势chase弱, 双错.
- 链接: 更正错16(G2输家不等于逆势SELL接刀整体); 错6/L13终极机制; 错12(软调和不硬门); 错9(勿凭印象/子集判断); 错14(1h/4h phase=HTF成熟度, 本节全量切). 证据PM-ENTRY-TRACE-RESULT-2026-09-10.md §8(双归档md5=7A941538). 候选=降权顺势追势子签名(C/D待拍板+5min证非自跑).

## 错18(验证skills假设, 错8的skills版) skills方法论claim须在我们BASE2验证非盲信; 本次Layer4多尺度极端0胜率空集证伪+1d/5d/10d S/R弱(2026-09-10)
- 现象: 偏信skills QUPM Layer4">=3/4多尺度极端追单0胜率"与"多周期S/R"可过滤入场. 经R5建两诊断任务(pm-multiscale-extreme-diag + pm-sr-multitf-diag)在我们150单验证: Layer4 ext_hi>=3 n=0空集(BASE2不在3+/4多尺度高位极端触发BUY) -> claim证伪/不适用; 1d/5d/10d近阻力BUY整体WR0.49+16.85(非输, 含突破赢单), 仅G1顺势反弹+1d近阻力n11 WR0.273弱细化. 数据准确性mismatch=0/traced=150.
- 规则18(验证非盲信skills): skills库方法论claim(胜率/效果)基于其当时数据窗/参数; 引入PM前必须在我们BASE2经R5 orchestrator验证(建诊断任务算同维度分桶核WR/pnl), 证立才C/D入库, 证伪/空集则弃(守错8). 不可因"成熟方法论"就直接上(=错8空架的skills版). 多周期S/R非独立杠杆, 仅边际锐化顺势追势弱信号(错16-17已捕获).
- 链接: 错8(实证非空架)/错9(读核非印象)/错16-17(逆势edge顺势弱). 候选D弃/F弱/E待测(SMC需库). 证据PM-MULTITF-VALIDATION-2026-09-10.md(双归档md5=41645932).


## 错19(结构化HH/LL识别 rank4 + 真分离器细化错16/17; 过程错 --config) 顺势+近HH顶追高=输家子集, 逆势/中立中位抄底=赢家子集; 粗趋势标签勿一刀切(2026-09-10 pm-swing-scene-diag)
- 现象: 用户问"LL/HH 重新寻找更好方案识别判断; 真正赚钱的逆势抄底是不同场景". 建 pm-swing-scene-diag 用 B1 已确认 4h/1d swing pivot 算 rank4(=(price-last4h低pivot)/(last4h高pivot-last4h低pivot), 近1=近HH顶/近0=近LL底) 作【结构化】HH/LL 识别, 替代 RCR 粗 4h_state. 趋势轴用 entry_trace macro4h(顺势/逆势/中性), 验证比 wrapper 自算 _st4(swing up/down/mixed) 分离更干净(macro4h顺势+hi n17 WR0.294 vs _st4 up+hi n15 WR0.400).
- 实测(独立手算CSV重切 + sloth-loop重跑双重复现, verify 3/3 PASS, 数字完全一致): BUY 真分离器 = macro4h × rank4: 顺势+近HH顶[0.65,1.0] weak_chase_buy n17 WR0.294 +0.231(最浓缩输家, 1h/4h涨后追未破的顶); 逆势/中性+中位[0.35,0.65) edge_buy n20 WR0.75 +12.198(逆势抄底dip, 占BUY总盈亏24.35的53%=利润引擎); bos_buy 真破last HH rank4>1.0 n5 WR0.8(真突破赢, 区别于追未破的顶). 关键反直觉: 抄底赚钱的是【中位回撤】非【极端底】(reversal_low rank4<0.35 n3 WR0.33弱). SELL小样本(n5-18)分离杂乱暂不提硬门.
- 规则19: (1)HH/LL 用结构化pivot位置(rank4)识别, 非粗 4h_state; (2)【粗趋势标签勿一刀切】——"顺势"内含输家子集(顺势+近HH顶追高), "逆势/中性"内含赢家子集(中位抄底), 须看【趋势方向 × 位置vs最近HH/LL】交叉分桶再判, 不能用macro4h单独当好/坏; (3)refine错16/17: 逆势抄底edge在中位回撤(非极底), 顺势追势弱在近HH顶追高(非全顺势) — 给更细可执行子集, 防"杀全顺势"(误杀顺势中位/破顶BOS) 或"全保逆势"(含逆势近HH fade); (4)过程子错: pm/嵌套项目 loop 触发用 --config 不用 --project(后者 _load_project 把 backtest.script 相对项目目录解析, 而config script是相对PROJECT_ROOT全路径 -> 路径双拼找不到, verify 0/3). 候选C(软调weak_chase降置信x0.8+needs_human+收紧出场, 非硬门)/D(确认edge不被压) 须用户拍板+5min证+双sim非自跑(守错12/错16-17 逆势抄底不可硬门阻).
- 链接: 承错16/17(逆势抄底edge/顺势追势弱)细化到 rank4 位置维度; 错13/14(reversal/continuation/rebound EXIT路由) — weak_chase近HH顶追高≈continuation追势弱入场, edge中位抄底≈reversal/早反弹; 错12(软调非硬门); 错11(大周期滞后用于事后软调和非抓启动, rank4用的last4h pivot是已确认结构=已形成非滞后); 错21预防(SELL小样本不提硬门勿过拟合). 证据 PM-SWING-SCENE-RESULT-2026-09-10.md 双归档 md5=89F5F7CECA00AD447074FFA105159A47. wrapper v2 projects/pm/pm-swing-scene-diag/wrapper.py(.bak_20260910_v1_rcr 备份旧RCR版).


## 错20 — orchestrator signals格式 + 长sim超时破invariant (2026-09-10, pm-diff-sl真sim)
- **现象**: orchestrator --config启动双sim, signals.json若为dict或有UTF-8 BOM -> signal-pool报错("must be JSON array"/"not valid JSON")不跑sim. PowerShell `Set-Content -Encoding UTF8` 自动加BOM坑. 正确格式=JSON数组 `[{{"signal_pattern":"xxx","market_condition":"..."}}]` 无BOM(用Python `json.dump`写, 或`utf-8-sig`读).
- **现象2**: 双sim各~11min超shell timeout(15min) -> 杀父进程 -> wrapper.finally未执行 -> SIM被留patched(DIFFSL)状态 = BASE2 invariant破坏. 
- **教训**: R5范式(备份->patch->双sim->finally恢复)本身可靠, 但orchestrator超时杀父绕过finally. **长sim必须**: (a)超时后立即`Get-Content SIM -match DIFFSL/F5 tag`检查并手动恢复BASE2 bak; (b)或后台跑+轮询+确认finally. invariant第一, 任何patch后必复核SIM=BASE2(本节已restore+复核25883字节无tag).
- **正例**: 本节真sim验证通过(+2.488, 三重铁证)且invariant已恢复, 即便中途超时也守住底线.

---

# 追加教训 2026-09-16 (PM复测任务被误解——如何正确理解用户目标)

## 教训1: 先锚定目标, 再谈执行
- 用户任务其实是"用正确口径复测既定140信号(T0001~T0150)的盈利有效性", 并要发起10轮全新验证; 后续下发其他币种信号沿用同一流程.
- 我错误理解为"为ETH/BTC/SOL自创候选信号", 于是造了一个BOS突破生成器(造轮子), 造得不对, 且用100x(已知不可行)跑, 得到全亏. 这不是验证, 是错误口径下的自证失败.
- 教训: 当输入是"既定信号集/既定流程"时, 任务是"复测/复用", 不是"重新生成". 严禁在不确认目标的情况下自创算法/造轮子.

## 教训2: 已失效结论(不变量)必须先规避, 不许重撞
- 知识库早已坐实"100x+1%强平 与 结构反转持有互斥"(ETH REAL100结论). 必须把该结果当不变量前置规避, 而不是再跑一遍100x. 
- 教训: 运行任何多币/复测之前, 先读对应RC/蒸馏里的失败结论(红色不变量), 直接采用正确档位, 不重复已否定的实验.

## 教训3: 承接用户思路后先复述确认, 不擅自起跑
- 我多次在没跟你确认"意图/口径/是否造轮子"情况下硬跑, 浪费大量token. 应在理解不确定时, 先花最短时间和你对齐(如"是否有现成BTC/SOL信号""用何口径"), 再执行.
- 教训: 模糊即确认; 不要用"自动执行"掩盖"我没听懂".

## 正确目标记录(供未来唤醒)
- 唯一目标: 复测ETH 140信号盈利有效性, 10轮全新验证; 输入=既定信号集(不造); 口径=无前瞻/合理杠杆止损按币价档/结构ChoCH分级止盈; 3轮MD5一致即确定性验收; 后续用户下发的其他币信号照同一流程. 严禁100x. 目标锚见 PM-TARGET-ANCHOR-2026-09-16.

## 错21 "静默失败掩盖" + "门禁恒红" (2026-10-16 全面体检 + L1 修复, next)

- 错1(fail-open): 输入加载失败时静默回退默认值(wrapper 缺失 / 信号 JSON 非法 / 配置缺键),
  CLI `--once` 与 continuous 仍返回 **rc=0**, 对外表现为 "completed/STOP"。根因: `run_once_pipeline` 把
  **失败**写成 `status="ok"`(未检查 act_result.status); `run_loop.run()` 吞掉异常不 return;
  continuous 连续错误计数("2 consecutive errors")也未置 rc=0。教训: **静默失败 = 假成功**——
  下游会把它当成果归档(靠 status/verdict), 必须让失败可见、rc 与状态一起冒泡。
- 错2(锁): `run_lock` 硬编码 6h 才判 stale, 崩溃后锁长时间卡死; 应记录 owner PID 判活。
  - 教训: 别把"超时"当成锁释放的唯一依据; 应做 **owner 存活判定**(进程在不在; 异常 → fail-safe 保守)。
- 错3(判定): `verifier._compare` 遇 operator 为 None 或 "unknown" 时 **默认通过**, 静默放行。
  - 教训: 判定器遇未知必须 **fail-closed(视为失败)**, 不能放过 unknown。
- 错4(门禁口径): `scripts/run_gate.py` 只跑 `pytest tests`, 而 pyproject `testpaths=["tests"]`+`source=["sloth_engine"]`
  只覆盖 tests cov 66.85% < fail_under=70, **与 HEAD 无关**; 应改为 `pytest tests sloth_engine/tests`(71.98%)。
  - 教训: **口径不一致会造出"恒红的门禁"**; 覆盖率来源必须与真实测试面一致, 否则只能 `--no-verify` 绕过(违背铁律10)。
- 证据: 错9(覆盖口径)与错8(输入校验)的延伸; 真实复现(REPRO_*.json)留档, 修复后逐项转绿;
  验收链: "输入校验 + OODA + 快照 md5 + 复现"四件套是可交付的最低要求。

## 错22 — 门禁两面不一致与静默降级第二批 (2026-10-16, L1 修复, next)

- **现象(质与形不一致)**: 同一套代码，两份独立测试包报告覆盖率 66.79% vs 71.83% —— 差异不在代码，在**依赖是否装齐**（缺 fastapi 等导致部分模块 0 覆盖）。两份包……各自都“正确”。
  - 教训: **口径里必须锁死依赖安装步骤**；否则“覆盖率低于门槛”是假性阻断，不能据此判 FAIL。
- **现象(门禁假阳性)**: `plugin_loader.purity_check` 用 `encoding="utf-8"` 读 `entry.py`，而发布包内 `dsh-rag-kb/entry.py` 带 UTF-8 BOM，`ast.parse` 报 `SyntaxError: invalid non-printable character U+FEFF`，门禁恒报“cannot parse entry.py”。
  - 根因: `read_text("utf-8")` 保留 BOM 字符；应用 `utf-8-sig`。**门禁自带假阳性 = 信噪比下降，真违规会被淹没**。
- **现象(静默吞错)**: `signal_pool.load` 只 catch `(OSError, JSONDecodeError)`，漏了 `UnicodeDecodeError`；GBK/非 UTF-8 signals 一旦出现就“静默返回空池”（无错无日志），用户看不到真原因。
  - 教训: 读外部文件的每个分支都要**fail-closed 且可诊断**，不可静默。
- **现象(fail-open 回退 + 误导性报错)**: `load_config` 缺文件时静默返回 defaults，之后报出的却是 `ContainmentError`（路径逃逸），与真因（配置缺失）无关。
  - 教训: “静默回退 → 报错错位”比直接报错更危险；用显式开关（`require_exists`）让入口 fail-closed，保留默认行为作**向后兼容**。
- **现象(型错崩栈)**: `verifier._compare` 遇 `threshold: "abc"` 无类型校验 → 无未捕获 `TypeError` 裸崩栈。
  - 教训: 判据引擎的输入必须**先校验后使用**，异常型判为 fail-closed 而非崩溃。
- **现象(门禁没有“电”)**: 交付/验收场景无 `.git` 或无 staged 变更时 `run_gate.py` 恒 SKIP(exit 0)，**验收方无法一键验门禁**。
  - 修法: 新增 `--all`，无视 git 状态直接跑全量门禁；默认（无 --all）保持 pre-commit 快速 SKIP。
- **共同教训(本批核心)**: 上一批修复了“失败不传播”（错21），但**同类病变体仍广泛存在**：假阳性、静默吞错、fail-open、型错崩栈、门禁假 SKIP。
  ⇒ **修完一个类别要扫全部“同病异位”**，不只修被举报的那一例；且**先复现(G-1)后修**，修后**三轮 md5 + 破框（真 CLI）**双验。
- 证据: `scripts/tmp/loopdev-retest/{g1_repro,retest}.py`、`postfix/round{1,2,3}.json` md5=cfd2d6efd2c3c92374535b7d3c04f8f3；全量 1184 passed / cov 72.01%。

## 错23 — “失败不传播”之后的剩余漏斗：隐式默认与“声称 fail-closed 实为 fail-open” (2026-10-17, L1 接口, next)

- **现象(隐式默认)**: 空 `success_criteria` 被调度器静默推导一组判据，跑完看起来“通过”，用户从未声明过它。
  - 教训: **默认值必须可见**；任何“用户没给、系统代填”都应 `[WARN]` + 落盘（如 `implicit_criteria`），不能静默。
- **现象(声称校验却放行)**: `schema_validate` 默认偏向放行（fail-open），与“强校验”宣称矛盾。
  - 教训: **安全开关默认必须是最严一侧(fail-closed)**；放宽要显式退(`=false`)。
- **现象(损坏状态静默降级)**: 损坏的 SQLite 被当作“空 DB”继续跑，错因丢失。
  - 教训: **体不存与空体是两回事**，损坏应 `CorruptDatabaseError`（可诊断、fail-closed）。
- **现象(证据只存派生不存原文)**: 报告里的 `input_ref` 指向硬编码路径，回溯时找不到当时真实输入/模型输出。
  - 教训: **证据链要到原文**；每轮把原始 I/O 复制进 `data/·` 并让 `input_ref` 指向它。
- **共同教训(本批核心)**: 批二修了“失败不传播”（错21），但**“声称安全实为安全漏洞”还是没扫完**：
  隐式默认 / 默认放行 / 损坏静默 / 证据无原文 —— 四个“同病异位”。
  ⇒ **对“fail-closed”这类安全声称，要逐个开关反向自检“默认到底哪一侧”**，并用契约不变量测试锁住。
- 证据: `work_ooda/20261017-093515-l1-batch3-five-fixes/`、
  `projects/loop/l1-batch3-five-fixes/reports/2026-10-17/REPORT.md`；全量 **1194 passed / 1 xfailed / coverage 72.13%**。
