# The Castle of Crossed Destinies

一个将七套本地命理 Skill 置于同一审计框架的案件工作台：八字、紫微斗数、西占、印占、数秘、人类图与 Dreamspell。访客上传已有报告，确认抽取事实后，才会让七个相互隔离的 Chamber 生成证词。

## 包含内容

- 每套体系分别上传 PDF、TXT/MD、PNG/JPG/WEBP/TIFF
- 文本 PDF 直接读取；扫描 PDF 与图片使用 Tesseract OCR
- 项目使用的六份 AI-readable TXT/JSON 由本地确定性解析器直接读取，不让模型猜字段；
  西占和印占优先保留核心盘面、分盘与时限层，最多 80 条事实
- DeepSeek 从本地取得的临时文字中只抽取显式盘面事实，并隔离原报告中的解释性文字
- 用户逐条修改、删除、补充和确认抽取事实
- 两种可切换的报告模式：实验自由模式与 Grounded Skills 引用审计模式
- 七个项目内、版本可控的 Chamber Skills：`skills/*-chamber/`
- 共享证据契约、受控主题词表、每套体系独立知识边界与来源
- 中性证词与人物语气分两次生成；Tribunal 只读取中性证词
- General report 只展开实际形成证词的栏目，未覆盖主题折叠保留供审计
- Tribunal 区分 genuine convergence、表面共识、直接冲突、侧重差异与不可比较
- 用户提问后：独立回答 → 主持人定向 challenge → 每室一次 rebuttal → 结案总结
- SQLite 案件保存与恢复令牌；API Key 和原始上传文件不进入数据库
- 没有可核验盘面事实时，不生成解释性结论

“证据不足”只用于确实需要补算或臆造缺失盘面的情况。一个已确认事实若能直接
匹配知识包规则，可以产生低置信度、有 caveat 的条件式解读；缺少次要 convention
只会降低置信度。若首轮输出因引用 ID 不合规而全部被过滤，后端会使用明确的
事实、规则和主题白名单自动重试一次。
所有报告及角色化开场均锁定为简体中文；非中文角色开场会被后端拒绝并回退到
中性中文证词。

### 两种报告模式

- **实验自由模式（默认）**：每间 chamber 只进行一次自然语言调用，不读取项目
  Skills，不要求 JSON、Evidence ID 或 Rule ID；随后用一次自然语言调用生成
  Tribunal。它更接近普通聊天式分析，也更快、更不容易因返回格式而整篇失败，
  但没有逐条引用审计，暂不执行结构化问答与 rebuttal。
- **Grounded Skills**：保留七套完整 Skills、规则白名单、证据引用、人物语气隔离、
  结构化 Tribunal 与一轮制交叉质询。它的调用次数更多，并可能拒绝未通过引用校验的
  内容。

切换模式不会删除 Skills 或已确认事实。案件恢复后可直接重新生成，无需重新上传。

## 启动

后端：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。前端开发服务器会把 `/api` 代理到 FastAPI。

## VPS / Docker

仓库包含可直接部署的 `compose.yml`、`Caddyfile` 和两个 Dockerfile。API 镜像会把项目的 `skills/` 目录复制到 `/skills`，供 DeepSeek chamber runner 读取。

```bash
docker compose up -d --build
curl http://127.0.0.1/api/health
```

案件数据库保存在 Docker named volume `castle_cases`，重新构建容器不会丢失。
一致性备份可使用：

```bash
docker compose exec api python -c "import sqlite3; s=sqlite3.connect('/data/castle.db'); d=sqlite3.connect('/data/castle-backup.db'); s.backup(d); d.close(); s.close()"
docker compose cp api:/data/castle-backup.db ./castle-backup.db
```

若希望访客在网页中安全填写 BYOK，请把域名解析到 VPS，在仓库根目录 `.env`
写入 `CASTLE_DOMAIN=castle.example.com` 后重新启动。Caddy 会自动申请 HTTPS；
直接以 IP 和 HTTP 访问时仍可测试，但 Key 的传输没有 HTTPS 保护。

## 工作流与隐私边界

1. `POST /cases` 建立案件，服务端只保存恢复令牌的 SHA-256 哈希。
2. `POST /cases/{id}/sources/{system}` 临时读取文件并抽取事实；原始文件不落盘。
3. `PUT /cases/{id}/facts/{system}` 保存用户确认后的事实及必要的短原文定位。
4. `POST /cases/{id}/reports` 并行生成独立报告，再召开 Tribunal。
5. `POST /cases/{id}/debates` 执行固定一轮的回答、质询、反驳和总结。
6. `GET /cases/{id}` 配合 `X-Case-Token` 恢复案件。

后端不会自行排盘。上传阶段，本地解析器先直接识别项目的结构化 TXT/JSON；其他
TXT/文本 PDF 由 DeepSeek 从临时文字中抽取显式事实，扫描件则先在本地运行 OCR。
原文件和完整文本不落盘。用户确认后，
后端只把每间 chamber 的已确认事实、共享证据契约、`SKILL.md` 与
`references/knowledge.md` 单独传给 DeepSeek；所有 claim 都必须
同时回指事实 ID 与知识包中的规则 ID。第一遍只生成中性证词，第二遍只根据
`references/persona.md` 改写语气。Tribunal 应始终使用 `neutral_statement`，
而不是人物化后的 `statement`。

上传限制为每份 15 MB。本地 PDF 最多处理前 40 页。数据库会保存用户确认后的事实、证词、
Tribunal 和辩论记录；不会保存原始 PDF/图片、完整 OCR 文本或 API Key。

## 配置 DeepSeek

支持两种方式：

1. **访客 BYOK**：在首页输入 Key。Key 只保存在当前页面内存，通过
   `X-DeepSeek-Key` 发送给后端后立即转发；不写入 localStorage、数据库或日志。
2. **自托管默认 Key**：复制并填写仅存放在服务器上的环境文件：

```bash
cp backend/.env.example backend/.env
```

```env
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_MODEL=deepseek-v4-flash
```

`DEEPSEEK_API_KEY` 仅由后端读取，绝不能放入前端代码或 Git。
公网 HTTPS 仍是正式部署的强烈建议。为方便初次在 VPS IP 上测试，页面不会阻止
HTTP 下填写 BYOK，但会显示明文传输风险警告；此时请只使用可随时撤销的测试 Key。
姓名、生日、出生时间、地点与时区均为可选，报告中已有时无需重复填写。

> 命理输出仅供反思与娱乐，不应用于医疗、法律、财务或其他重大决定。
