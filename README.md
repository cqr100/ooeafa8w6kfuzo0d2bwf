# mihomo-mrs-rules

域名清单 → 自动编译成 [mihomo](https://github.com/MetaCubeX/mihomo) 的 **MRS** 规则集。

仓库地址：`https://github.com/cqr100/mihomo-mrs-rules`（私有）

## 怎么加域名

只改一个文件：**`rules/emby.list`**

```yaml
DOMAIN,em.mlhyy.top #茉莉
DOMAIN,cn.mlhyy.top #茉莉.cdn
```

加一行 → Commit → 等约 1 分钟 → `dist/emby.mrs` 自动更新。

网页编辑：https://github.com/cqr100/mihomo-mrs-rules/edit/main/rules/emby.list

## 支持的写法

| 写法 | 编译成 | 匹配范围 |
| --- | --- | --- |
| `DOMAIN,example.com` | `example.com` | 精确匹配，只命中 example.com 本身 |
| `DOMAIN-SUFFIX,example.com` | `+.example.com` | 后缀匹配，example.com + 所有子域名 |
| `example.com` | `+.example.com` | 同上（不写前缀默认按后缀） |
| `=example.com` | `example.com` | 精确匹配 |
| `.example.com` | `.example.com` | 只匹配子域名 |
| `*.example.com` | `*.example.com` | 只匹配一级子域名 |

- `#` 后面是注释，随便写，不影响编译
- 空行忽略，大小写不敏感，重复的自动去重
- **只认域名**。`SUB-RULE`、`IP-CIDR`、`RULE-SET` 这类规则装不进规则集，写进去会构建失败并报出行号

## 文件结构

```
rules/emby.list       ← 唯一要改的文件
build/emby.txt        规范化后的中间产物（自动生成，可读）
dist/emby.mrs         最终规则集（自动生成，给 mihomo 用）
scripts/build.py      编译脚本
```

## 在 mihomo 里用

**永久链接**（实测 mihomo 可正常远程拉取）：

- 跟随最新版：`https://raw.githubusercontent.com/cqr100/mihomo-mrs-rules/main/dist/emby.mrs`
- 锁定某个版本（内容永不变化）：把上面的 `main` 换成 commit SHA

仓库是私有的，**链接必须带 token**，裸链返回 404（GitHub 硬限制）。配置：

```yaml
rule-providers:
  mrs-emby:
    type: http
    behavior: domain
    format: mrs
    interval: 86400
    proxy: DIRECT
    header:
      Authorization:
        - "token {只读PAT}"          # 私有仓库必须带，无鉴权返回 404
    url: "https://raw.githubusercontent.com/cqr100/mihomo-mrs-rules/main/dist/emby.mrs"
    path: ./ruleset/mrs-emby.mrs

rules:
  - RULE-SET,mrs-emby,{你的Emby策略组}
  - GEOIP,CN,DIRECT
  - MATCH,PROXY
```

`{只读PAT}` 建议单独建一个 Fine-grained token：只授权 `mihomo-mrs-rules` 这一个仓库，权限只给 **Contents: Read-only**。别把账号级的 classic token 写进配置文件。

### 复用已有的 `mrsdomain` 锚点

如果你 config 里已经有

```yaml
mrsdomain: &mrsdomain {type: http, interval: 86400, behavior: domain, format: mrs}
```

**不用改它**，用 YAML 合并键 `<<:` 引用就行（已实测 mihomo 支持）：

```yaml
rule-providers:
  mrs-emby:
    <<: *mrsdomain
    proxy: DIRECT
    header:
      Authorization:
        - "token {只读PAT}"
    url: "https://raw.githubusercontent.com/cqr100/mihomo-mrs-rules/main/dist/emby.mrs"
    path: ./ruleset/mrs-emby.mrs
```

要点：

- 锚点里已有 `type / interval / behavior / format`，provider 只需补 `url` / `path`（私有仓库再加 `header`）
- 自己写的键会**覆盖**锚点里的同名字段，比如想缩短更新间隔就单独写 `interval: 3600`
- 每个 provider 的 `path` 必须不同，否则多个 provider 会共用同一个缓存文件，内容互相覆盖
- 多个 provider 想复用同一套认证，再定义一个锚点，一行合并两个（已实测可用）：

```yaml
mrsauth: &mrsauth
  proxy: DIRECT
  header:
    Authorization:
      - "token {只读PAT}"

rule-providers:
  mrs-emby:
    <<: [*mrsdomain, *mrsauth]
    url: "https://raw.githubusercontent.com/cqr100/mihomo-mrs-rules/main/dist/emby.mrs"
    path: ./ruleset/mrs-emby.mrs
```

改完规则集后 mihomo 不会立刻生效（有 `interval` 缓存），重启内核或调 `PUT /providers/rules/mrs-emby` 强制刷新。

## 本地编译（可选）

```bash
python scripts/build.py --download-mihomo   # 首次：自动下载 mihomo 到 bin/
python scripts/build.py                     # 之后：直接编译
```

需要 Python 3.9+。也可以自己装好 mihomo 后设 `MIHOMO_BIN` 环境变量指过去。

平时不用本地跑，push 后 Actions 会自动编译并提交 `dist/`。
