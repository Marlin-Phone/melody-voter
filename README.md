# melody-voter · 网易云音乐合伙人自动化助手

自动完成网易云音乐「音乐合伙人」每日基础评分 + 额外评分任务，并引入结算期达标提醒。

## 功能特性

| 能力 | 说明 |
|------|------|
| 🎯 评分策略引擎 | 适配 2026-09 新评分映射规则，星级权重可配，5% 抖动防呆 |
| 💬 自动评论加分 | 评分时自动附上随机短评（每首约 +1 分），语料池可配 |
| 🔢 动态任务上限 | 实时读取当日可选额外任务数并做满（不写死上限） |
| 👥 多账号支持 | `accounts` 数组，账号间随机间隔防关联 |
| 📊 积分账本 + 达标提醒 | 本地记录每日完成量，按 28 天结算期估算距达标线还差几首 |
| 📱 扫码登录工具 | 本机二维码登录，自动写回本地 Cookie（仅本机/家庭网络可用，服务器会被风控拦截） |
| 🔔 邮件通知 | Cookie 失效 / 执行失败 / 完成摘要（SMTP） |

## 目录结构

```
melody-voter/
├── main.py               # 入口（执行 / --report 报告）
├── tools/
│   └── login.py          # 扫码登录，自动写回 Cookie
├── config/
│   └── setting.example.json
└── src/
    ├── signer.py         # weapi 加密 + ScoreEngine 评分引擎
    ├── tasks.py          # 基础/额外任务执行
    ├── ledger.py         # 结算期账本与达标估算
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
   python main.py --report     # 只看当前结算期达标进度
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
3. Actions 页可手动 Run workflow 测试；之后每天自动执行
4. Cookie 约两周过期，失效后：
   1. 在**你的电脑**（家庭网络）重新 `python tools/login.py` 扫码更新本地 `config/setting.json`
   2. 重新执行上面的 base64 命令，把新值覆盖到 Secret `SETTING_JSON_B64`
   3. 手动 Run workflow 验证（可看 Actions 日志确认 Cookie 有效）

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
      "enable_comment": true,    // 评分附带评论（+1分/首）
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

## 结算期提醒逻辑

- 网易云每 **28 天** 一个结算期（周一 00:00 起，如 11.09 ~ 12.06），达标约需 **320 积分**
- **结算期与达标线均无需配置**：代码内置锚点（74 期 = 2026-11-09）按 28 天自动滚动切分（75 期 = 12.07、76 期 = 01.04 …）；达标线内置 320，若平台调整改 `src/ledger.py` 的 `TARGET_POINTS` 即可
- 每次运行把「完成/失败」记入 `data/ledger/<name>.jsonl`
- 估算：每首约 3 分（实际 1~5 视评分），`--report` 输出还差几首、剩余几天
- ⚠️ 估算仅供参考，以 App「我的记录」为准

## 风险提示

- 本质是模拟人工操作，网易云风控可能拦截（行为验证码 8821 等），请合理设置频率
- 被识别作弊会回收奖励 / 封号；本项目仅供学习交流
- Cookie 约两周过期，到期后重新 `python tools/login.py`

## 致谢

感谢原项目 `ACAne0320/ncmp` 提供的逆向接口参考与社区实践。
