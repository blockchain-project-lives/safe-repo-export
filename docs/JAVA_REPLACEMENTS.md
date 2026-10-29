# Java 方法体替换 / Java method-body replacement

[中文 README](../README.zh-CN.md) · [English README](../README.md) · [默认规则](DEFAULT_RULES.md)

将核心方法体替换为你提供的模拟实现，保留方法定义，供接收方编译、开发和调试外围代码。**只修改导出副本，绝不修改源仓库。**
Replace selected business method bodies with supplied mocks, retaining declarations for downstream development. Only the export copy is changed.

## 初始化 / Initialize

```sh
safe-repo-export init
```

除六份 `.list` 外，还补齐以下文件；已有文件不覆盖。示例默认禁用，单独运行 init 不会开启替换。
In addition to six lists, init creates the following missing files without overwriting existing files. The example is disabled by default.

```text
.safe-repo-export/
├── replacements.yaml
├── stubs/
│   └── example-method-body.java.txt
└── safe-repo-export-*.list
```

默认配置 / Default config:

```yaml
replacements: []
```

## 配置 / Configure

将空列表替换成真实规则 / Replace the empty list with actual rules:

```yaml
replacements:
  - file: src/main/java/com/example/FeeService.java
    class: com.example.FeeService
    method: calculateFee
    parameter-types:
      - Order
      - BigDecimal
    body-file: stubs/calculate-fee.java.txt
```

| 字段 / Field | 含义 / Meaning |
|---|---|
| `file` | 相对仓库根目录的 Java 文件路径 / Java path relative to the repository root |
| `class` | 完整包名＋类名；嵌套类使用 `com.example.Outer.Inner` / Fully qualified class name; dots for nested classes |
| `method` | 方法名，不包括返回类型 / Method name without return type |
| `parameter-types` | 按声明顺序填写类型；无参数使用 `[]` / Ordered parameter types; `[]` for no arguments |
| `body-file` | 相对仓库 `.safe-repo-export/`，且必须位于 `stubs/` 内 / Relative to repository `.safe-repo-export/`, inside `stubs/` |

推荐模板使用 `.java.txt`，避免 IDE 将方法体片段当作完整 Java 编译单元。模板读取不限制扩展名，已有 `.java` 模板仍可使用；若自行改名，请同步修改 `body-file`。`init` 不会改名或删除已有模板，只补齐缺失的新示例。
Use `.java.txt` to avoid IDE errors for incomplete Java compilation units. Template loading is extension-independent; existing `.java` files still work. Update `body-file` when renaming. Init preserves old files and only adds missing new demos.

模板只写**大括号内部**的 Java 内容，不写方法定义或外围大括号，例如 `.safe-repo-export/stubs/calculate-fee.java.txt`：
Templates contain only the body contents, not the method declaration or enclosing braces:

```java
// Export-only mock; not the real business implementation.
return FeeResult.of(BigDecimal.ZERO);
```

原始方法 / Original:

```java
package com.example;

import java.math.BigDecimal;

public class FeeService {
    public FeeResult calculateFee(Order order, BigDecimal amount) {
        // Core business logic to keep private.
        BigDecimal rate = loadPrivateRate(order);
        return FeeResult.of(amount.multiply(rate));
    }
}
```

导出结果保留签名、注解、修饰符、泛型、参数名、返回类型、throws，仅替换方法体 / Only the body changes:

```java
public FeeResult calculateFee(Order order, BigDecimal amount) {
    // Export-only mock; not the real business implementation.
    return FeeResult.of(BigDecimal.ZERO);
}
```

多个规则在 `replacements:` 下继续添加 `  - file: ...`。同一文件可指定多个不同方法，不允许重复指定同一签名。
Add more `  - file: ...` entries for multiple methods. Repeated selection of the same signature is rejected.

## 类型匹配 / Type matching

- 方法体可以任意变化；只要目标路径、类名、方法名及参数类型不变，仍能定位。
- 参数名不参与定位，`final` 和参数/类型注解不参与匹配。**模板若使用参数名，重命名参数后仍须更新模板**。
- 类型按 Java 源码的文字匹配，忽略空白；不解析 imports、不推导继承或类型别名。源码写 `BigDecimal` 就配置 `BigDecimal`；源码写 `java.math.BigDecimal` 就配置完整名称。
- 泛型完整填写，例如 `"Map<String, List<Order>>"`。保留类型实参顺序，`List<Order>` 与 `List<String>` 不同。
- 支持数组及 varargs：`String[]`、`String names[]` 的类型为 `String[]`；`String...` 与 `String[]` 归一化匹配。
- 重载由有序参数类型区分；返回类型不参与定位。

Match the path, class, method and ordered textual parameter types. Ignore type whitespace, annotations, `final` and parameter names; normalize varargs to arrays. There is no import/type resolution. Mocks referencing renamed parameters must be updated even though selection still succeeds.

## 导出 / Export

```sh
# 调试：读工作区最新规则、模板及已跟踪源码，无需提交
# Debug: current working rules/templates and tracked Java sources; no commit needed
safe-repo-export --worktree --output ../sanitized --replace

# 默认：读 HEAD 中的规则、模板与源码
# Default: rules, templates and sources from HEAD
safe-repo-export --output ../sanitized
```

也可用 `--ref` 导出其他 commit/tag/分支，该版本必须包含规则和模板；`--allow-dirty` 不会切换为工作区规则。
`--ref` reads all inputs from that committed version. `--allow-dirty` still uses committed rules/templates.

工作区模式允许规则和模板尚未暂存；目标 Java 文件仍必须是已跟踪路径，新 Java 文件先 `git add`。替换在路径过滤后、脱敏和扫描前执行。模板中若有真实凭据，也会进入普通源码脱敏流程。
Working rules/templates need not be staged. Target Java files must be tracked (stage new Java files). Replacement runs after path filtering and before redaction/scanning, so recognizable credentials in templates are also handled.

## 失败与输出 / Failure and output

- 每条规则要求恰好一个有方法体的方法。目标缺失/被过滤、类或方法找不到/匹配多个、模板缺失、重复签名均阻止导出。
- 目标不能命中 `sanitize-skip`，避免替换内容绕过脱敏和扫描。
- 路径禁止绝对地址、`..`、反斜杠、`.git` 等不安全内容；规则/模板及其父目录不能是软链接。模板必须在 `.safe-repo-export/stubs/`。
- `.safe-repo-export/replacements.yaml` 和整个 `.safe-repo-export/stubs/` **总是从正常导出副本及归档中移除**，即使替换为空或未启用；include/skip 不能保留它们。其他 `.list` 继续按原规则处理。
- `EXPORT-REPORT.md` 只记录规则序号、目标文件和次数，不记录原方法体、模板正文或私有规则内容。
- 替换错误会中止本次输出安装；已有输出保持原样，不会退回导出未替换的核心方法。

Missing, excluded, ambiguous, abstract or unsupported targets fail closed. No source/index changes occur. Private YAML/templates never enter normal exports/archives. Reports contain rule numbers, paths and counts only. Failed exports preserve prior output.

## 首版语法边界 / Initial syntax limits

实现只依赖 Python 标准库，是保守的 Java 词法/结构定位器，**不是完整 Java 编译器或语义解析器**：

- 支持普通类、静态/实例方法、重载、嵌套类、常见泛型/注解/数组/varargs；忽略注释、字符串、字符字面量和 text block 内的大括号，处理嵌套代码块和匿名类。
- 不支持替换构造器、无方法体的 abstract/interface 方法、receiver parameter（如 `Outer this`）。
- 目标 Java 文件或模板出现 Java `\uXXXX` Unicode 转义时拒绝处理，避免 Java 预词法转义改变结构；直接 UTF-8 注释/文本不受这条限制。
- 不做完整语义验证：模板检查括号和字面量结构，但**不会自动编译**，也不验证返回类型、引用、异常和副作用。请在导出后运行目标项目的编译/测试。
- 保留方法体外的代码、Javadoc、注释、imports 和其他方法；若这些也泄漏业务信息，需要另行处理。

Stdlib only; conservative structural matching, not semantic Java analysis. Unsupported/ambiguous structures stop export. Constructors, bodyless methods, receiver parameters and Java Unicode escapes are unsupported. Templates are checked lexically, not compiled; validate the exported project yourself. Content outside selected bodies is preserved.

配置文件使用受限 YAML：仅支持上述顶层 block 列表、固定五个字段、字符串值、block 参数列表和空列表 `[]`；缩进为规则 2 空格、字段 4 空格、参数项 6 空格。支持 `#` 注释、单引号、JSON 兼容双引号字符串；不支持 anchors、aliases、tags、flow 规则对象、inline 非空参数列表或多行 scalar。未知/重复字段和不支持的写法报错，不会静默跳过。
The restricted YAML schema accepts the generated block layout, five fields, string scalars and block parameter lists (or `[]`). Indent rules/fields/parameter items by 2/4/6 spaces. Comments, single quotes and JSON-compatible double quotes work; anchors, aliases, tags, flow rule objects, nonempty inline parameter lists and multiline scalars do not.
