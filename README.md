# mihomo-mrs-rules

用自己的域名清单，自动编译出 [mihomo](https://github.com/MetaCubeX/mihomo) 的 **MRS** 格式规则集。

改 `rules/*.list` → push → GitHub Actions 自动生成 `dist/*.mrs` 并提交回仓库。不用本地装任何东西。

仓库地址：`https://github.com/cqr100/mihomo-mrs-rules`（私有）

## 目录结构

```
rules/          你手写的域名清单（唯一需要改的地方）
build/          规范化后的中间产物（自动生成，可读）
dist/           最终 .mrs 规则集（自动生成，给 mihomo 用）
snippets/       不能编译成 .mrs、只能粘贴进 config.yaml 的规则片段
scripts/build.py 编译脚本（本地 / CI 通用）
config.example.yaml  mihomo 引用示例
```

## 日常用法

1. 打开 `rules/proxy.list`，加一行 `newdomain.com`
2. commit + push
3. 等 Actions 跑完（约 1 分钟），`dist/proxy.mrs` 已更新

Actions 只在 `rules/`、`scripts/` 或 workflow 本身变动时触发，手动重建在 Actions 页面点 **Run workflow**。

## 规则写法

每行一条，空行和 `#` 注释忽略，大小写不敏感。

| 写法 | 编译成 | 匹配范围 |
| --- | --- | --- |
| `example.com` | `+.example.com` | example.com 本身 + 所有子域名（**默认，推荐**） |
| `+.example.com` | `+.example.com` | 同上，显式写法 |
| `.example.com` | `.example.com` | 只匹配子域名，不含 example.com 本身 |
| `*.example.com` | `*.example.com` | 只匹配一级子域名 |
| `=example.com` | `example.com` | 精确匹配，只匹配 example.com |

> 注意：mihomo 原生 `domain` 规则集里，裸域名是**精确匹配**。本仓库把裸域名自动补成 `+.`（后缀匹配），因为手写清单时 99% 的场景都是想匹配整个站点。真要精确匹配请写 `=example.com`。

新增清单文件：在 `rules/` 下新建 `xxx.list`，不用改 workflow，下次构建自动带上。

> 校验规则很严：任何一行写错（域名带空格、误粘 classical 规则）都会让构建**直接失败**并在 Actions 里报出具体行号，不会静默丢弃。静默丢一条规则 = 某个站点悄悄不走代理，比报错难查得多。

## 哪些规则进不了 .mrs

`SUB-RULE` 这类规则**不能**编译成规则集。mihomo 会明确拒绝（实测）：

```
parse classical rule [SUB-RULE,(DOMAIN,em.mlhyy.top),sub-rule-emby-n] error:
unsupported rule type on classical rule-set: SUB-RULE
```

原因：`SUB-RULE` 的第二个参数指向 `sub-rules:` 里定义的规则链，而规则集是独立文件，没有这个上下文。所以这类规则只能写在 `config.yaml` **顶层**的 `rules:` 里。

`SUB-RULE`、`DOMAIN-SUFFIX`、`IP-CIDR`、`RULE-SET` 这些带逗号的路由规则都属于这种情况，统一放 `snippets/`：

```
snippets/emby.rules.yaml   Emby 相关规则，可直接粘到 config.yaml 的 rules: 下
```

`snippets/*.yaml` 里的内容是**完整可粘贴的 YAML 片段**（带 `- ` 前缀），不参与编译，也不会被 build.py 处理。

注意：`snippets/emby.rules.yaml` 依赖你 `config.yaml` 里已有的 `sub-rules:` 定义（`sub-rule-emby`、`sub-rule-emby-n`）和 `IP@cloudflare` 这个 rule-set provider，缺任何一个都会启动失败。

## 本地编译

```bash
python scripts/build.py --download-mihomo   # 自动下载 mihomo 到 bin/ 再编译
python scripts/build.py                     # 内核已就绪时直接编译
python scripts/build.py proxy reject        # 只编译指定列表
```

需要 Python 3.9+。也可以自己装好 mihomo 后设置 `MIHOMO_BIN` 环境变量指过去。

## 在 mihomo 里引用

完整示例见 `config.example.yaml`。核心就是：

```yaml
rule-providers:
  mrs-proxy:
    type: http
    behavior: domain
    format: mrs
    interval: 86400
    header:
      Authorization:
        - "token {YOUR_READONLY_PAT}"
    url: "https://raw.githubusercontent.com/cqr100/mihomo-mrs-rules/main/dist/proxy.mrs"
    path: ./ruleset/mrs-proxy.mrs

rules:
  - RULE-SET,mrs-proxy,PROXY
```

### 私有仓库怎么读？

`raw.githubusercontent.com` 对私有仓库要鉴权，无鉴权直接返回 404（已实测），而 mihomo 本身没有登录概念，所以三选一：

1. **带 token 拉取**（当前默认方案，已实测 200 可用）——配置里写死一个只读 PAT。`Authorization: token xxx` 和 `Bearer xxx` 两种写法都行。建议用 fine-grained token，只授权这一个仓库、只给 Contents 读权限，泄露风险可控。
2. **同步到公开仓库**——workflow 已内置 `publish` job：在 Settings → Variables 建 `PUBLIC_REPO=用户名/仓库名`，Secrets 建 `PUBLISH_TOKEN`（对该公开仓库有写权限的 PAT），之后每次构建自动把 `dist/*.mrs` 同步过去，mihomo 用公开 URL 匿名拉取，配置文件里不用放 token。
3. **本地文件**——同一台机器上跑 mihomo 的话，`type: file` 指向克隆下来的 `dist/proxy.mrs`，配个定时 `git pull` 就行，完全不联网。

## 为什么用 MRS

- 体积小：同样内容通常只有 YAML 的 1/5 到 1/3
- 加载快：二进制结构，启动时不用解析文本
- 内存省：路由器的低配设备上差别明显

## 版本

`mihomo` 内核版本由 `scripts/build.py` 自动取**最新 release**，想锁版本就改 `scripts/build.py` 里的 `RELEASE_API` 指向具体 tag。
