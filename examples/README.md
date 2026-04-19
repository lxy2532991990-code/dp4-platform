# DP4 Platform 示例数据

本目录包含用于测试 DP4 平台的示例数据。

## 目录结构

每个测试目录包含：
- `experimental_assignments.csv` - 实验 NMR 化学位移分配
- `opt_conf/` - 构象优化输出文件
- `nmr_opt_60_roots/` - NMR 屏蔽计算输出文件

## 使用方法

运行 DP4 分析：

```bash
cd examples/test1
dp4-platform --candidates-root . --exp-nmr-file experimental_assignments.csv
```

## 注意事项

- 输出文件（`.out`、`.log`、`.xyz`、`.inp`）已通过 `.gitignore` 排除
- 仅保留配置文件供参考
- 实际使用时可替换为自己的计算数据