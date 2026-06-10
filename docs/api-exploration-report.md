# 新浪财经行情中心数据接口探查报告

**日期**: 2026-06-09
**目标页面**: `https://vip.stock.finance.sina.com.cn/mkt/#sw_sysh`

## 一、API 接口清单

### 1. 实时行情接口（已在用）

```
GET https://hq.sinajs.cn/rn={timestamp}&list={symbols}
Header: Referer: https://finance.sina.com.cn/
返回: var hq_str_{symbol}="字段1,字段2,..."
编码: GB2312
```

### 2. 列表数据接口（新发现）

```
GET https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData
参数:
  - node: 节点代码（如 sh_a, sw_sysh, gn_hwqc）
  - sort: 排序字段（symbol, changepercent, volume, amount, per, pb, mktcap, turnoverratio）
  - asc: 0=降序 1=升序
  - page: 页码（从 1 开始）
  - num: 每页条数（20/40/80）
Header: Referer: https://vip.stock.finance.sina.com.cn/
返回: JSON 数组
编码: UTF-8
```

返回字段：
```json
{
  "symbol": "sh600000",      // 代码
  "code": "600000",          // 纯数字代码
  "name": "浦发银行",        // 名称
  "trade": "9.550",          // 最新价
  "pricechange": 0.18,       // 涨跌额
  "changepercent": 1.921,    // 涨跌幅（%）
  "buy": "9.540",            // 买入价
  "sell": "9.550",           // 卖出价
  "settlement": "9.370",     // 昨收
  "open": "9.370",           // 今开
  "high": "9.560",           // 最高
  "low": "9.340",            // 最低
  "volume": 52684975,        // 成交量（股）
  "amount": 498861812,       // 成交额（元）
  "ticktime": "10:58:59",    // 时间
  "per": 6.283,              // 市盈率
  "pb": 0.422,               // 市净率
  "mktcap": 31807075.5765,   // 总市值（万元）
  "nmc": 31807075.5765,      // 流通市值（万元）
  "turnoverratio": 0.15819   // 换手率（%）
}
```

### 3. 节点树接口（新发现）

```
GET https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodes
Header: Referer: https://vip.stock.finance.sina.com.cn/
返回: 嵌套 JSON 数组（树形结构）
编码: UTF-8
```

树结构格式：
```json
[
  "行情中心",
  [
    ["A股", [
      ["新浪行业", [
        ["玻璃行业", "", "new_blhy"],   // [名称, URL, 节点代码]
        ...
      ]],
      ["申万行业", [
        ["石油石化", "", "sw_sysh"],
        ...
      ]]
    ]],
    ["港股", [...]],
    ["美股", [...]]
  ],
  ...  // 可能还有更多顶层分类
]
```

---

## 二、全部可选节点

### A 股市场

| 节点代码 | 说明 |
|----------|------|
| `hs_a` | 沪深 A 股（全部） |
| `sh_a` | 沪市 A 股 |
| `sz_a` | 深市 A 股 |
| `bjs_root` | 北交所 |
| `hs_b` / `sh_b` / `sz_b` | B 股 |
| `kcb` | 科创板 |
| `cyb` | 创业板 |
| `delist_st` | 退市警示 |
| `shfxjs` | 风险警示板 |
| `hgt_sh` | 沪股通 |
| `sgt_sz` | 深股通 |
| `aplush` | A+H 股 |

### 申万行业分类（三级体系，共 499 个节点）

| 层级 | 节点前缀 | 数量 |
|------|---------|------|
| 一级行业 | `sw_` | 31 |
| 一级行业(编码) | `sw1_` | 31 |
| 二级行业 | `sw2_` | 131 |
| 三级行业 | `sw3_` | 337 |

一级行业完整列表（`sw_` 前缀）：
`sw_sysh`(石油石化), `sw_mt`(煤炭), `sw_mrhl`(美容护理), `sw_hb`(环保), `sw_dlsb`(电力设备), `sw_jdhy`(家电), `sw_yyhy`(医药), `sw_sphy`(食品饮料), `sw_jrhy`(金融), `sw_fdc`(房地产), `sw_txbh`(通信), `sw_jsj`(计算机), `sw_cmn`(传媒), `sw_qc`(汽车), `sw_jxhy`(机械), `sw_jzjc`(建筑材料), `sw_fzzs`(纺织服饰), `sw_nyhy`(农林牧渔), `sw_qghy`(轻工制造), `sw_gfjs`(国防军工), `sw_ylfw`(社会服务), `sw_shh`(综合), `sw_jtys`(交通运输), `sw_dzqj`(电子), `sw_ylqx`(美容护理), `sw_bjhy`(有色金属), `sw_iron`(钢铁), `sw_xc`(基础化工), `sw_dl`(电力), `sw_mech`(机械设备), `sw_gysb`(公用事业)

### 新浪行业分类（49 个）

节点前缀 `new_`，如 `new_blhy`(玻璃), `new_dlhy`(电力), `new_gthy`(钢铁), `new_dzxx`(电子信息), `new_qczz`(汽车制造), `new_jzjc`(建筑建材) 等。

### 概念板块（913 个）

| 节点前缀 | 数量 | 示例 |
|----------|------|------|
| `gn_` | 214 | `gn_hwqc`(华为汽车), `gn_BCdc`(BC电池), `gn_hwhm`(华为鸿蒙), `gn_gykc`(高压快充) |
| `chgn_` | 699 | `chgn_701381`(物理AI), `chgn_730605`(锂电隔膜), `chgn_730604`(英特尔概念) |

### 指数（41+ 个）

节点前缀 `zhishu_*`，如 `zhishu_000001`(上证指数), `zhishu_000688`(科创50)。
其他: `hs_s`(所有指数), `dpzs`(大盘指数), `zhzs`(中华系列)

### 地域板块（31 省市）

节点前缀 `diyu_*`，如 `diyu_310000`(上海), `diyu_440000`(广东), `diyu_110000`(北京)

### 基金

| 节点代码 | 说明 |
|----------|------|
| `open_fund` | 开放式基金 |
| `money_fund` | 货币型基金 |
| `crefund` | 创新型基金（分级） |
| `etf_hq_fund` | ETF 行情 |
| `etf_jz_fund` | ETF 净值 |
| `lof_hq_fund` | LOF 基金 |
| `jjycjz` | 基金预测净值 |
| `close_fund` | 封闭式基金 |
| `kcb_fund` | 科创板基金 |

### 港股

| 节点代码 | 说明 |
|----------|------|
| `qbgg_hk` | 全部港股 |
| `hk_hshy*` | 港股行业（38 个） |
| `lcg_hk` | 蓝筹股 |
| `gqg_hk` | 国企股 |
| `hcg_hk` | 红筹股 |
| `zs_hk` | 港股指数 |
| `hot_hk` | 热门港股 |

### 期货（60+ 品种）

节点后缀 `_qh`，涵盖：
- 贵金属: `hj_qh`(黄金), `by_qh`(白银), `pt_qh`(铂), `pd_qh`(钯)
- 有色金属: `tong_qh`(铜), `lv_qh`(铝), `ni_qh`(镍), `xi_qh`(锡), `xing_qh`(锌), `qian_qh`(铅)
- 黑色系: `tks_qh`(铁矿石), `jm_qh`(焦煤), `jt_qh`(焦炭), `lwg_qh`(螺纹钢), `rzjb_qh`(热轧卷板), `gt_qh`(硅铁), `mg_qh`(锰硅)
- 能源化工: `yy_qh`(原油), `ry_qh`(燃油), `lu_qh`(低硫燃料油), `pg_qh`(液化石油气), `pta_qh`(PTA), `yec_qh`(乙二醇), `pvc_qh`(PVC), `lldpe_qh`(乙烯), `cj_qh`(纯碱), `lc_qh`(碳酸锂)
- 农产品: `lh_qh`(生猪), `hym_qh`(玉米), `mh_qh`(棉花), `dp_qh`(豆粕), `dy_qh`(豆油), `czy_qh`(菜油), `jd_qh`(鸡蛋), `pk_qh`(花生)
- 股指期货: `qz_qh`(沪深300), `szgz_qh`(上证50), `zzgz_qh`(中证500), `im_qh`(中证1000)
- 国债期货: `engz_qh`(2年期), `gz_qh`(5年期), `sngz_qh`(10年期), `tl_qh`(30年期)

### 外汇

| 节点代码 | 说明 |
|----------|------|
| `jbhl_forex` | 基本汇率 |
| `jchl_forex` | 交叉盘汇率 |
| `cny_forex` | 人民币相关 |
| `usd_forex` | 美元相关 |
| `all_forex` | 所有汇率 |
| `hot_forex` | 热门汇率 |

### 美股

| 节点代码 | 说明 |
|----------|------|
| `china_us` | 中国概念股 |
| `usstock_new` | 全部美股 |
| `tect_us` | 科技类 |
| `finance_us` | 金融类 |
| `auto_us` | 汽车能源类 |
| `sales_us` | 制造零售类 |
| `meida_us` | 媒体类 |
| `yysp_us` | 医药食品类 |

---

## 三、JS 文件清单

| 文件 | URL | 用途 | 行数 |
|------|-----|------|------|
| hqzx.js | `//n.sinaimg.cn/finance/66ceb6d9/20241106/hqzx.js` | 主行情控制，所有 S_SL_* 数据类 | 6923 |
| hq_js20200316.js | `//n.sinaimg.cn/finance/hqzxpclrr/hq_js20200316.js` | 工具函数 | 185 |
| stock_list_cn.js | `//vip.stock.finance.sina.com.cn/mkt/js/stock_list_cn.js` | A 股列表 S_SL_CN 定义 | 338 |
| IO.Script_1_0_1.js | `//i3.sinaimg.cn/cj/HKstock2007/IO.Script_1_0_1.js` | JSONP 脚本加载器 | — |
| ssologin.js | `//i.sso.sina.com.cn/js/ssologin.js` | SSO 登录 | — |
| cardtips.js | `//i.sso.sina.com.cn/js/cardtips.js` | 卡片提示 | — |
| FinanceAppPics.js | `//finance.sina.com.cn/other/src/FinanceAppPics.js` | 图片 banner | — |
| mkt_obs_hk.js | `//finance.sina.com.cn/other/src/mkt_obs_hk.js` | 港股样式观察 | — |
| SuggestServer*.js | `//www.sinaimg.cn/cj/financewidget/js/SuggestServer_14_04_22_gb.js` | 搜索建议 | — |

---

## 四、数据类清单（hqzx.js 中的 S_SL_* 类）

| 类名 | 对应节点 | 数据类型 | 关键字段 |
|------|---------|---------|---------|
| `S_SL_CN` | `sh_a/sz_a/hs_a` | A 股行情 | symbol, name, trade, pricechange, changepercent, buy, sell, settlement, open, high, low, volume, amount, per, pb, mktcap, nmc, turnoverratio |
| `S_SL_ANH` | `aplush` | A+H 股 | symbol, name, trade, changepercent, hrap(AH溢价率) |
| `S_SL_BOND` | `hs_z/sh_z/sz_z` | 债券 | symbol, name, trade, changepercent, volume, amount |
| `S_SL_CREFUND` | `crefund` | 可转债 | symbol, name, trade, changepercent, volume, amount |
| `S_SL_FUND` | `open_fund` | 基金 | symbol, name, dwjz(单位净值), ljdwjz(累计净值), nav_chg(净值变动), jjgm(基金规模) |
| `S_SL_FUNDMONEY` | `money_fund` | 货币基金 | symbol, name, dwjz, ljdwjz, per万份收益, seven_day(7日年化) |
| `S_SL_FUNDNET` | `jjycjz/etf_jz_fund` | 基金净值 | name, time, nav_chg, pre_nav, last_nav, accu_nav, wfzs |
| `S_SL_FUTURES` | `hj_qh/tong_qh/...` | 期货 | symbol, name, trade, changepercent, open, high, low, volume, amount, hold(持仓), yclose(昨结) |
| `S_SL_FOREX` | `jbhl_forex/...` | 外汇 | symbol, name, trade, changepercent, open, high, low |
| `S_SL_GLOBAL` | `global_qh` | 全球期货 | symbol, name, trade, changepercent, open, high, low, volume |
| `S_SL_CNMR` | `stock_hs_up/down` | 涨跌排行 | symbol, name, trade, changepercent, volume, amount, mr_percent(涨速) |
| `S_SL_ADR` | `adr_hk` | 港股 ADR | symbol, chname, last, chg, pchg, prevclose, open |
| `S_SL_UK` | `lse_star` | 英股 | symbol, cname, price, chg, changepercent, volume, totalPrice |

---

## 五、关键发现

1. **列表数据 API 比实时行情 API 字段更丰富**：包含 per(市盈率), pb(市净率), mktcap(总市值), nmc(流通市值), turnoverratio(换手率) — 这些是量化分析的基础数据
2. **申万三级行业分类完整可用**（31+131+337=499 个节点），是行业轮动策略的基础
3. **概念板块数据极其丰富**（214+699=913 个概念），是事件驱动策略的基础
4. **期货数据覆盖 60+ 品种**，可做跨市场联动分析
5. **港股/美股数据也可获取**，为跨境投资提供数据支撑
6. **所有数据接口共享同一个 JSONP API 路径**，只需切换 `node` 参数即可获取不同市场数据
7. **当前系统只用了 `hq.sinajs.cn` 一个接口**，未利用列表数据 API 的丰富字段

---

## 六、下一步建议

| 优先级 | 内容 | 价值 |
|--------|------|------|
| ⭐⭐⭐ | 接入列表数据 API（per/pb/mktcap/nmc/turnoverratio） | 多因子策略基础数据 |
| ⭐⭐⭐ | 接入申万行业分类（sw_/sw1_/sw2_/sw3_） | 行业轮动策略 |
| ⭐⭐ | 接入概念板块（gn_/chgn_） | 事件驱动策略 |
| ⭐⭐ | 接入期货数据（_qh） | 跨市场联动 |
| ⭐ | 接入港股/美股 | 跨境投资 |
