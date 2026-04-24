# ECD-Platform

**面向天然产物绝对构型解析的高容错 ECD 工作流平台**

A fault-tolerant ECD workflow platform for absolute configuration determination of natural products, directly from ORCA outputs — no SpecDis dependency.

---

## 五大创新点

### 创新点 1：容错型构象匹配框架 (`matcher.py`)
- 综合文件名后缀、输入区块 `xyzfile` 引用自动配对 OPT ↔ ECD 文件
- 冲突检测（重复编号、孤立文件）
- 导出 `conformer_mapping.csv` 映射表，支持人工校正后重新加载
- 解决 SpectroIBIS 对严格编号和顺序一致性的强依赖

### 创新点 2：构象级异常隔离 (`conformer.py`)
- 每个构象独立维护状态机：`OK / NO_ENERGY / IMAGINARY_FREQ / PARSE_FAILED / ...`
- 坏构象自动隔离，好构象继续参与 Boltzmann 加权
- 异常报告自动生成（`conformer_status.txt`）
- 解决 SpectroIBIS "提取数量不一致即整批报错" 的问题

### 创新点 3：虚频容差与加权策略可配置 (`energy.py`)
- 三种虚频策略：STRICT / TOLERANT / MANUAL
- 可配置阈值（如 `< -10 cm⁻¹` 才剔除）
- 支持四种能量来源：电子能、Gibbs 自由能、高层级单点、手动权重
- 温度敏感性分析接口
- 专为天然产物柔性体系的小虚频问题设计

### 创新点 4：ORCA → 最终 ECD 图的完整闭环 (`spectrum.py` + `report.py`)
- 直接从 ORCA 输出解析 CD 数据
- Gaussian 展宽、Boltzmann 加权、归一化、对映体生成
- Publication-ready PNG + Origin-compatible CSV
- 无需 SpecDis / BIL 中间格式

### 创新点 5：实验谱自动比较与 AC 判定 (`comparison.py`)
- Shift 扫描：在能量平移范围内找最优匹配
- 多种相似度指标：cosine / pearson / tanimoto
- 自动测试对映体（倒置谱）
- 置信度评估（high / medium / low）
- 多候选异构体排名接口

---

## 安装

仅需 Python 3.8+ 和 NumPy（matplotlib 可选但推荐）：

```bash
pip install numpy matplotlib
```

将 `ecd_platform/` 目录放在项目根目录下即可使用。

---

## 快速开始

### 方式 1：Python 脚本

```python
from ecd_platform import ECDPipeline, ECDConfig, ImagFreqPolicy

config = ECDConfig(
    opt_dir='opt_conf',
    ecd_dir='ecd_opt_60_roots',
    exp_file='experiment.csv',
    sigma=0.3,
    shift=0.15,
    scale_factor=5.0,
    imag_freq_policy=ImagFreqPolicy.TOLERANT,
    imag_freq_threshold=-10.0,
)

pipeline = ECDPipeline(config)
pipeline.run()
```

### 方式 2：命令行

```bash
python -m ecd_platform \
    --opt-dir opt_conf \
    --ecd-dir ecd_opt_60_roots \
    --exp-file experiment.csv \
    --sigma 0.3 \
    --shift 0.15 \
    --scale 5.0 \
    --imag-freq-policy tolerant \
    --imag-freq-threshold -10.0
```

### 方式 3：从配置文件复现

```bash
python -m ecd_platform --config config.json
```

---

## 输出文件说明

运行后在 `ecd_results/` 下生成：

| 文件 | 说明 |
|------|------|
| `analysis_report.txt` | 完整分析报告（配置、权重、AC 判定） |
| `ecd_comparison_*.png` | Publication-ready ECD 对比图 |
| `shift_scan.png` | Shift 扫描曲线图 |
| `ecd_data_*.csv` | 计算谱 + 实验谱插值数据 |
| `config.json` | 参数存档（可复现） |
| `conformer_mapping.csv` | 构象匹配映射表（可人工校正） |
| `conformer_status.txt` | 构象异常报告 |
| `pipeline.log` | 运行日志 |

---

## 文件命名规则

平台默认识别 `conf-N`、`conformer-N`、`M####` 等后缀模式。也可自定义正则：

```python
config = ECDConfig(
    filename_pattern=r'myprefix[_-](\d+)',  # 匹配 myprefix-1, myprefix_23 等
)
```

---

## 模块架构

```
ecd_platform/
├── __init__.py        # 公开 API (ECDPipeline / ECDConfig / 枚举)
├── __main__.py        # python -m 入口
├── config.py          # 配置管理（ECDConfig + WeightingStrategy / ImagFreqPolicy / CDGauge）
├── conformer.py       # 构象状态机 & 集合管理
├── matcher.py         # 容错型构象匹配
├── parser.py          # ORCA 输出解析（能量/频率/CD）
├── energy.py          # Boltzmann 权重计算
├── spectrum.py        # Gaussian 展宽 & 加权叠加
├── experimental.py    # 实验谱读取 & 平滑（FFT / Savitzky-Golay）
├── comparison.py      # 相似度评分 & AC 判定
├── report.py          # 可视化 & 报告生成
├── pipeline.py        # 主编排器（7 步工作流）
├── cli.py             # 命令行接口
├── gui.py             # PyQt6 桌面图形界面（构象匹配可视化编辑）
└── example_usage.py   # 使用示例脚本
```

项目根目录额外包含：

- `run_gui.py` — GUI 启动器（等价于 `python -m ecd_platform.gui`）
- `run.py` — 脚本式调用示例
- `build_qt.bat` — PyInstaller 一键打包脚本

### GUI 启动方式

```bash
python run_gui.py              # 直接运行启动器
python -m ecd_platform.gui     # 作为模块运行
ecd-platform-gui               # pip install 后可用的命令
```

---

## 与现有工具的对比

| 特性 | SpectroIBIS + SpecDis | ECD-Platform |
|------|----------------------|--------------|
| 文件匹配 | 严格编号/顺序一致 | 自动匹配 + 冲突检测 + 人工校正 |
| 异常处理 | 整批报错 | 构象级隔离，好构象继续 |
| 虚频策略 | `< 0` 一律剔除 | 可配置阈值 + 三种策略 |
| 权重来源 | 固定 | 电子能 / Gibbs / 单点 / 手动 |
| 出图 | 需 SpecDis | 直接生成 publication-ready 图 |
| AC 判定 | 手动比较 | 自动 shift 扫描 + 评分 + 置信度 |
| 可复现性 | 依赖操作记录 | config.json 完整存档 |

---

## 下一步开发建议

1. **Benchmark 验证**：选取 6-10 个已知绝对构型的天然产物，覆盖低/中/高柔性体系
2. **GUI 界面**：基于 PyQt/Tkinter 添加图形化映射校正界面
3. **VCD/OR 扩展**：复用相同架构支持 VCD 和旋光度数据
4. **机器学习辅助**：训练模型预测最优 σ 和 shift 参数
