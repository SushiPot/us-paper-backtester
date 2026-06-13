# 美股模拟交易系统

本项目包含两个阶段：

- 第一阶段：离线回测
- 第二阶段：本地模拟盘，不需要券商账户
- 第三阶段：保留 IBKR Paper Trading 模块，但默认不启用

默认推荐使用本地模拟盘：不连接 IBKR，不需要券商账户，不会发送任何真实或模拟券商订单。IBKR 代码保留在项目里，但只有你手动运行 `paper_main.py` 才会尝试连接。

## 功能

- 标的：TSLA、NVDA、AAPL、SPY、QQQ
- 数据源：yfinance 历史日线
- 备用数据：如果当前网络导致 yfinance 无法返回数据，会自动切换到 Yahoo Chart 历史接口，并缓存到 `data_cache/`
- 策略：
  - MA20 上穿 MA60
  - RSI(14) < 70
  - 当日成交量大于 20 日平均成交量
- 卖出：
  - MA20 下穿 MA60
  - 止损 -8%
  - 止盈 +20%
  - 持仓超过 30 个交易日
- 仓位：
  - 初始资金 10000 美元
  - 单笔仓位不超过总权益 20%
  - 最多同时持仓 5 只
  - 禁止杠杆、融券、期权
- 风控：
  - 每日最大亏损 2%
  - 账户最大回撤 10%
  - 触发后停止交易并记录日志
- 输出：
  - `outputs/trade_log.csv`
  - `outputs/backtest_report.csv`
  - `outputs/equity_curve.png`

## 本地模拟盘

没有 IBKR 账户、没有任何券商账户，也可以直接运行本地模拟盘。

运行方式：

```powershell
cd C:\Users\rog\Documents\GPTprogram\us_paper_backtester
python local_paper_main.py --once
```

本地模拟盘规则：

- 不连接 IBKR
- 不需要券商账户
- 使用 `yfinance`，失败时自动使用 Yahoo Chart 历史接口
- 使用 `virtual_cash` 模拟资金，初始资金 10000 美元
- 使用 `outputs/positions.csv` 保存虚拟持仓
- 使用 `outputs/paper_order_log.csv` 保存虚拟订单
- 使用 `outputs/paper_trade_log.csv` 保存虚拟成交
- 使用 `outputs/virtual_account.csv` 保存虚拟现金和权益
- 使用 `outputs/account_history.csv` 保存账户权益历史
- 自动生成 `outputs/local_paper_report.csv` 和 `outputs/local_equity_curve.png`
- 每天运行一次：`python local_paper_main.py --once`
- 单笔仓位不超过权益 20%
- 最多同时持仓 5 只
- 禁止杠杆、做空、期权
- 默认模拟 0.05% 滑点
- 默认手续费为每股 0.005 美元，最低 1 美元
- 每次运行默认只允许一个订单决策，避免重复交易

本地模拟盘输出：

- `outputs/positions.csv`
- `outputs/virtual_account.csv`
- `outputs/account_history.csv`
- `outputs/paper_order_log.csv`
- `outputs/paper_trade_log.csv`
- `outputs/decision_log.csv`
- `outputs/run_log.csv`
- `outputs/local_paper_report.csv`
- `outputs/local_equity_curve.png`

本地模拟盘借鉴了几个成熟项目的设计思路，但保持轻量：

- `backtesting.py`：清晰的订单、成交、持仓分层
- `pyfolio / empyrical`：权益曲线、最大回撤、夏普比率
- `PyPortfolioOpt`：保留组合层面的仓位和敞口统计入口
- `vectorbt`：保留后续批量参数测试的可扩展结构

## 回测运行

```powershell
cd C:\Users\rog\Documents\GPTprogram\us_paper_backtester
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

如果 Windows 的 `python` 命令指向 Microsoft Store 占位符，请在 VS Code 里选择真实的 Python 3.12 解释器后再运行。

## IBKR Paper Trading

IBKR 代码保留备用，但默认不启用。只有运行下面命令才会尝试连接 IBKR：

```powershell
python paper_main.py --once
```

新增配置位于 `src/config.py`：

```python
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 7497
IBKR_CLIENT_ID = 1
DRY_RUN = True
ALLOW_LIVE_TRADING = False
```

安全规则：

- 只允许账户号以 `DU` 开头的 IBKR Paper Account
- 检测到非 Paper Account 会立即抛出异常并停止
- `ALLOW_LIVE_TRADING=True` 会被拒绝启动
- `DRY_RUN=True` 时只打印和记录订单，不调用 `placeOrder`
- 只有手动改成 `DRY_RUN=False`，并且账户通过 Paper 校验，才会向 IBKR Paper Trading 发送模拟订单
- 市价单强制 `outsideRth=False`，并且程序只在美股常规交易时间运行
- 只创建 `STK` 股票合约，不创建期权合约
- 卖出数量不能超过当前多头持仓，避免做空

输出文件：

- `outputs/paper_order_log.csv`
- `outputs/paper_trade_log.csv`
- `outputs/paper_risk_log.csv`
- `outputs/paper_position_state.csv`

## IBKR 运行监控

IBKR 运行监控入口仍是 `paper_main.py`，但本项目当前默认推荐本地模拟盘。需要 IBKR Paper Account 时再使用：

```powershell
python paper_main.py --once
```

启动后会先打印运行前确认界面：

- 当前账户号
- 是否 Paper Account
- 当前 `DRY_RUN` 状态
- 当前 `ALLOW_LIVE_TRADING` 状态
- 当前持仓
- 当前现金、可用资金、账户权益
- 今日是否美股交易日
- 当前是否美股正常交易时间

硬性退出条件：

- 今日不是美股交易日
- 当前不是美股正常交易时间
- 账户不是 `DU` 开头
- `ALLOW_LIVE_TRADING=True`
- 网络中断或 IBKR 连接异常
- 行情数据为空
- 实时/延迟价格为空、为 0、NaN
- 实时/延迟价格相对最新历史收盘价波动超过 30%

确认界面通过后，需要手动输入：

```text
YES
```

才会继续生成本次唯一一次订单决策。`--yes` 可以跳过确认，但只建议你在明确知道自己仍处于 `DRY_RUN=True` 和 Paper Account 时使用。

第三阶段新增日志：

- `outputs/run_log.csv`
- `outputs/decision_log.csv`
- `outputs/safety_log.csv`

`decision_log.csv` 字段：

- 时间
- 股票代码
- 信号类型
- 是否满足买入条件
- 是否满足卖出条件
- 是否通过风控
- 是否 dry_run
- 是否实际发送到 Paper
- 拒绝原因

## TWS / IB Gateway 设置

TWS Paper Trading：

1. 启动 Trader Workstation
2. 登录时选择 Paper Trading
3. 确认账户号以 `DU` 开头
4. 打开 `Global Configuration -> API -> Settings`
5. 勾选 `Enable ActiveX and Socket Clients`
6. Paper TWS 默认端口通常是 `7497`
7. 确认 `Read-Only API` 不影响 dry run；真正发送 Paper 模拟单前需要允许 API 下单

IB Gateway Paper Trading：

1. 启动 IB Gateway
2. 登录 Paper Trading
3. Paper Gateway 常用端口是 `4002`
4. 如果使用 Gateway，把 `IBKR_PORT` 改为 `4002`

## Paper Trading 运行步骤

本地模拟盘推荐步骤：

```powershell
cd C:\Users\rog\Documents\GPTprogram\us_paper_backtester
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python local_paper_main.py --once
```

IBKR Paper Trading 备用步骤：

```powershell
cd C:\Users\rog\Documents\GPTprogram\us_paper_backtester
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python paper_main.py --once
```

## 重要说明

回测版本和本地模拟盘所有成交均为本地模拟成交。没有券商账户也能跑本地模拟盘。IBKR 版本只作为备用模块保留，且仍然默认 `DRY_RUN=True`、`ALLOW_LIVE_TRADING=False`。
