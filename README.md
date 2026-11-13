# melody-voter · 网易云音乐合伙人自动化助手

自动完成网易云音乐「音乐合伙人」每日基础评分 + 额外评分任务，并跟踪结算期达标进度（账本估算 + 平台实际积分实时查询）。

## 功能特性

| 能力 | 说明 |
|------|------|
| 🎯 评分策略引擎 | 适配 2026-09 新评分映射规则，星级权重可配，5% 抖动防呆 |
| 💬 乐评预检 + 自动评论 | 每首评分前评论先过平台内容预检（antispam，对齐 Web 端流程）再提交，确保「打分歌曲留言 +1/首」被记入任务（缺预检则评论只贴出、不记分） |
| 🎖️ 平台实际积分实时查询 | `user/info/get` + `home/get` 查当前期积分/等级/状态，TG 每日报告首行直显 |
| 🔢 动态任务上限 | 实时读取当日可选额外任务数并做满（不写死上限） |
| 🔁 同日去重 / 快速失败 | 运行前先探测账本：今天已有完成记录 → 直接跳过、零平台调用（防同日重复评分被平台批量拒，制造风控信号） |
| 👥 多账号支持 | `accounts` 数组，账号间随机间隔防关联 |
| 📊 积分账本 + 达标提醒 | 按官方评分表估算距达标线还差几首几分（满日 23 分 + 乐评至多 20 分） |
| 📱 扫码登录工具 | 本机二维码登录，自动写回本地 Cookie（仅本机/家庭网络可用，服务器会被风控拦截） |
| 🔔 TG Bot 通知 | 每日报告（含平台实际积分）/ Cookie 失效 / 运行异常 / 失败兜底告警（GitHub Secrets 注入），邮件通道可选保留 |

## 目录结构

```
melody-voter/
├── main.py               # 入口（执行 / --report 报告）
├── tools/
│   └── login.py          # 扫码登录，自动写回 Cookie
├── config/
│   └── setting.example.json
├── .github/workflows/
│   └── daily.yml         # 每日 09:00（北京时间）定时 + 账本缓存 + TG 通知
└── src/
    ├── signer.py         # weapi 加密 + ScoreEngine 评分引擎 + 乐评预检
    ├── tasks.py          # 基础/额外任务执行
    ├── ledger.py         # 结算期账本与达标估算（官方评分表）
    ├── points.py         # 平台实际积分实时查询（当前期/等级/状态）
    └── utils.py          # 配置/日志/Cookie校验/通知
```

## 快速开始

1. 安装依赖（国内镜像）：
   ```bash
   pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
   ```
2. 复制并编辑配置：
   ```bash
   cp config/setting.example.json config/setting.json
   ```
3. 获取 Cookie（任选其一）：
   - **推荐扫码（须在家庭/住宅网络执行）**：`python tools/login.py --account main`，手机 App 扫码后自动写入本地 `config/setting.json`
     ⚠️ 扫码是**本机操作**，只在你自己电脑上执行；在服务器 / 云主机 / GitHub Actions 上扫会被网易云风控拦截（行为验证码 8821）
   - 手动：登录 music.163.com → F12 打开开发者工具 → Network 面板 → 刷新页面 → 点击任意一个请求（如 `api/nuser/account/get` 或页面首屏接口）→ 在 Request Headers 里找到 `Cookie:` 一长串 → 从中复制 `MUSIC_U=...` 和 `__csrf=...` 两个字段的值，填入 `config/setting.json`
4. 运行：
   ```bash
   python main.py              # 执行今日任务
   python main.py --report     # 只看当前结算期达标进度（账本估算）
   python main.py --account main   # 只跑指定账号
   ```

## GitHub Actions 自动运行（推荐）

每天 09:00（北京时间）自动完成当日任务，无需本机常驻：

> **Cookie 的两段式流程**：扫码只在你的本机做（写入本地 `config/setting.json`，该文件不会进 GitHub）；Actions 只消费仓库 Secret `SETTING_JSON_B64`，两者通过手动更新 Secret 衔接。

1. 打开仓库 Settings → Secrets and variables → Actions → New repository secret
2. 名称填 `SETTING_JSON_B64`，值填 base64 编码的 `config/setting.json`：
   ```bash
   base64 -w0 config/setting.json   # macOS/Linux
   # Windows PowerShell: [Convert]::ToBase64String([IO.File]::ReadAllBytes("config\setting.json"))
   ```
3. （可选）配置 TG Bot 通知：再新增两个 Secrets——
   - `TG_BOT_TOKEN`：任意 Telegram bot 的 token（@BotFather 创建）
   - `TG_CHAT_ID`：接收通知的 chat ID

   配置后每次运行结束会推 TG 消息（**平台实际积分** + 完成/失败数 + 结算期达标进度）；Cookie 失效、运行异常时推详细告警；workflow 其他环节失败时补发兜底告警。不配置则不打扰（本地跑同理：未设 `TG_BOT_TOKEN`/`TG_CHAT_ID` 环境变量时静默跳过）
4. Actions 页可手动 Run workflow 测试；之后每天自动执行
5. Cookie 约两周过期，失效后：
   1. 在**你的电脑**（家庭网络）重新 `python tools/login.py` 扫码更新本地 `config/setting.json`
   2. 重新执行上面的 base64 命令，把新值覆盖到 Secret `SETTING_JSON_B64`
   3. 手动 Run workflow 验证（可看 Actions 日志确认 Cookie 有效）

> **账本持久化**：结算期账本（`data/ledger/`）经 Actions cache 跨 run 持久化——每次 run 的 workspace 是全新的，不缓存的话每期累计只算当次。同日多次 dispatch 会因去重直接跳过，不会重复提交平台。

## 配置项说明（config/setting.json）

```jsonc
{
  "accounts": [                                     // 账号列表（多账号按数组依次运行，账号间自动随机间隔防关联）
    {
      "name": "main",            // 账号标识（账本/日志用，如 main / 小号）
      "Cookie_MUSIC_U": "...",   // Cookie·MUSIC_U（登录凭证，扫码登录自动写入）
      "Cookie___csrf": "...",    // Cookie·__csrf（反爬令牌，扫码登录自动写入）
      "wait_time_min": 15,       // 单次操作随机等待下限（秒）
      "wait_time_max": 20,       // 单次操作随机等待上限（秒）
      "score_weights": {"1": 10, "2": 10, "3": 15, "4": 25, "5": 40},
                                 // 评分星级权重（1星~5星出现概率，合计100）。
                                 // 2026-09 新映射：中庸 3-4 星准确率低，押"好5差1"才准，
                                 // 默认押注中高分，可按个人听感调整
      "jitter": true,            // 5% 概率随机星级，防长期分布过于一致
      "extra_task_limit": 0,     // 额外任务上限，0=做满当日全部（平台每日最多15）
      "enable_comment": true,    // 评分附带乐评评论（经预检后 +1分/首，日上限20分）
      "comment_pool": ["旋律上头", "…"]   // 随机评论语料池（随机取一条附在评分后）
    }
  ],
  "notify_email": "",                 // 可选：通知邮箱（SMTP 收件人=发件人，留空不通知）
  "email_password": "",               // 可选：邮箱 SMTP 授权码（非登录密码）
  "smtp_server": "",                  // 可选：SMTP 服务器地址（如 smtp.qq.com）
  "smtp_port": 465,                   // 可选：SMTP 端口（465=SSL）
  "debug": false                      // 调试模式：true 输出更多日志（MELODY_VOTER_DEBUG=1 等效）
}
```

> TG 通知的 bot token / chat ID **不写进本配置文件**，而是经 GitHub Actions Secrets（`TG_BOT_TOKEN` / `TG_CHAT_ID`）注入环境变量；本地运行时同样通过这两个环境变量开启。

## 评分规则与达标估算

- 网易云每 **28 天** 一个结算期（周一 00:00 起，如 11.09 ~ 12.06），达标 **320 积分**（保持合伙人身份），400/480 分别为资深/首席称号；结算后清零
- **结算期与达标线均无需配置**：代码内置锚点（74 期 = 2026-11-09）按 28 天自动滚动切分（75 期 = 12.07、76 期 = 01.04 …）；达标线内置 320，若平台调整改 `src/ledger.py` 的 `TARGET_POINTS` 即可
- **官方评分表**（来源：官方攻略图 + 接口 `daily/task/get` 的 `dailyTaskScoreLimit` 字段，两者交叉验证）：

  | 渠道 | 项目 | 积分 | 上限 | 发放 |
  |------|------|------|------|------|
  | 歌曲评定·基础 | 每日完成 5 首歌曲评定 | +8 | 23 分/日 | 完成后立即 |
  | 歌曲评定·基础 | 每日 5 首后每多评定 1 首 | +1/首 | （含在 23 分/日内） | 完成后立即 |
  | 歌曲评定·基础 | 每日完成打分歌曲的留言（乐评） | +1/首 | 20 分/日 | 完成后立即 |
  | 歌曲评定·质量 | 1★/5★ 误差≤0.5；0.5<误差≤1；2-4★ 误差≤0.5 | +3 或 +2/首 | 60/40/40 | 每周一发（误差=与大众评分的偏差，需贴近大众分才得） |
  | 歌曲推荐·基础 | 发布 1 条公开笔记 / 乐评 | +2/条 · +1/条 | 6 · 3 | 完成后立即 |
  | 歌曲推荐·质量 | 7 日内有效互动 ≥7（笔记）/ ≥5（乐评） | +2/条 | 无上限 | 第 7 日 10 点前 |
  | 额外奖励 | 每周评定数 >0 且推荐数 >0 | +10/周 | — | 每周一 |

  *「有效互动」指非作者本人其他用户的真实评论/点赞。质量分是浮动大头但难以自动化稳定获取（上期实测精准率 21%）。*

- 本项目稳定收益 = **23 分/日**（基础 8 + 额外 15×1）+ 乐评留言 **至多 20 分/日**（预检流程已内置）；质量分与推荐渠道（公开发布笔记/乐评）未覆盖
- 每次运行把「完成/失败」记入 `data/ledger/<name>.jsonl`（Actions 侧经 cache 跨 run 持久化）；`--report` 输出账本估算；**TG 每日报告首行是平台实际积分**（`src/points.py` 实时查询，最权威）
- ⚠️ 账本估算仅供参考；以平台实际积分为准（App「我的记录」或 TG 报告首行）

### 乐评（评论）记分流程

评分时每首附带一条评论（语料池随机）。平台流程：**评论先过内容预检**（`custom/content/antispam`，带 taskId/workId/评论内容），**再提交评分**（`work/evaluate`）。缺预检时评论文本会贴到歌曲页，但**不记入合伙人任务记录**，+1/首 不发放（2026-11-13 实测确认）。预检在 `src/signer.py` 于每次评分前自动进行；预检失败时优雅降级（仅告警，不影响评分）。

## 风险提示

- 本质是模拟人工操作，网易云风控可能拦截（行为验证码 8821 等），请合理设置频率
- 官方「音乐合伙人」规则将「通过自动化工具、脚本或其他非正式的技术手段进行刷分」明确列为恶意刷分行为（可能取消身份/回收奖励）；本项目仅供学习交流，**使用后果自负**
- 被识别作弊会回收奖励 / 封号；建议控制频率、保持行为随机
- Cookie 约两周过期，到期后重新 `python tools/login.py`

## 致谢

- `ACAne0320/ncmp` —— 逆向接口参考与社区实践
- `crossgg/netease-cloud-music`（`api/weapi/partner.go`，HAR 抓包生成的完整 partner 接口面）—— 实际积分查询 / 乐评预检端点参考来源
- 官方「音乐合伙人详细攻略」长图（App 内 `home/get` 接口的 `ruleUrl`）—— 评分规则表参考
