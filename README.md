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
| 📱 扫码登录工具 | 二维码登录自动写回 Cookie（登录"扫一扫"即可） |
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
   - **推荐扫码**：`python tools/login.py --account main`，手机 App 扫码后自动写入
   - 手动：登录 music.163.com → F12 → Network → 取 `MUSIC_U` / `__csrf`
4. 运行：
   ```bash
   python main.py              # 执行今日任务
   python main.py --report     # 只看当前结算期达标进度
   python main.py --account main   # 只跑指定账号
   ```

## GitHub Actions 自动运行（推荐）

每天 09:00（北京时间）自动完成当日任务，无需本机常驻：

1. 打开仓库 Settings → Secrets and variables → Actions → New repository secret
2. 名称填 `SETTING_JSON_B64`，值填 base64 编码的 `config/setting.json`：
   ```bash
   base64 -w0 config/setting.json   # macOS/Linux
   # Windows PowerShell: [Convert]::ToBase64String([IO.File]::ReadAllBytes("config\setting.json"))
   ```
3. Actions 页可手动 Run workflow 测试；之后每天自动执行
4. Cookie 约两周过期，失效后重新 `python tools/login.py` 扫码，更新 secret 即可

## 配置项说明（config/setting.json）

```jsonc
{
  "accounts": [
    {
      "name": "main",            // 账号标识（账本/日志用）
      "Cookie_MUSIC_U": "...",   // Cookie
      "Cookie___csrf": "...",    // Cookie
      "wait_time_min": 15,       // 单次操作随机等待下限（秒）
      "wait_time_max": 20,       // 上限（秒）
      "score_weights": {"1": 10, "2": 10, "3": 15, "4": 25, "5": 40},
                                 // 评分星级权重。新机制下"好5差1"才准，
                                 // 默认押注中高分，可自行调整
      "jitter": true,            // 5% 概率随机星级，防长期分布过于一致
      "extra_task_limit": 0,     // 额外任务上限，0=做满当日全部
      "enable_comment": true,    // 评分附带评论（+1分/首）
      "comment_pool": ["旋律上头", "…"]   // 随机评论语料
    }
  ],
  "period_start_date": "2026-10-12",  // 当前结算期开始日（用于达标估算）
  "target_points": 320,               // 每期达标积分线
  "notify_email": "",                 // 可选：通知邮箱（SMTP）
  "email_password": "",
  "smtp_server": "",
  "smtp_port": 465,
  "debug": false
}
```

## 结算期提醒逻辑

- 网易云每 **28 天** 一个结算期（如 10.12 ~ 11.08），达标约需 **320 积分**
- `ledger.py` 按 `period_start_date` 起每 28 天滚动切分结算期
- 每次运行把「完成/失败」记入 `data/ledger/<name>.jsonl`
- 估算：每首约 3 分（实际 1~5 视评分），`--report` 输出还差几首、剩余几天
- ⚠️ 估算仅供参考，以 App「我的记录」为准

## 风险提示

- 本质是模拟人工操作，网易云风控可能拦截（行为验证码 8821 等），请合理设置频率
- 被识别作弊会回收奖励 / 封号；本项目仅供学习交流
- Cookie 约两周过期，到期后重新 `python tools/login.py`

## 致谢

感谢原项目 `ACAne0320/ncmp` 提供的逆向接口参考与社区实践。