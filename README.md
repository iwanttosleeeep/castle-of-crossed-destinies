# The Castle of Crossed Destinies

一个让七种象征体系独立阅读、彼此回应的案件工作台：八字、紫微斗数、西占、印占、数秘、人类图与 Dreamspell。访客只需上传已有报告，确认抽取事实后，七间 Chamber 才会生成证词。

## 包含内容

- 每套体系分别上传 PDF、TXT/MD、PNG/JPG/WEBP/TIFF
- 文本 PDF 直接读取；扫描 PDF 与图片使用 Tesseract OCR
- 项目使用的六份 AI-readable TXT/JSON 由本地确定性解析器直接读取，不让模型猜字段；
  西占和印占优先保留核心盘面、分盘与时限层，最多 80 条事实
- DeepSeek 从本地取得的临时文字中只抽取显式盘面事实，并隔离原报告中的解释性文字
- 用户逐条修改、删除、补充和确认抽取事实
- 单一轻量流程：每室的人物性格＋紧凑防幻觉契约＋自然语言长文
- 原七套完整知识包保留在 `skills/*-chamber/` 作为归档资料，不进入当前运行路径
- 首页不采集姓名、生日、时间、地点或时区
- Markdown 标题、列表、粗体、斜体、引用与行内代码安全渲染
- Tribunal 区分 genuine convergence、表面共识、直接冲突、侧重差异与不可比较
- 用户提问后：独立回答 → 每室一次 rebuttal → 主持人结案总结
- 一键导出完整 Markdown 案卷：确认事实、七份报告、Tribunal 与所有庭审记录
- 结束庭审后清空当前浏览器会话并返回新案件；服务器旧案仍可凭令牌恢复
- SQLite 案件保存与恢复令牌；API Key 和原始上传文件不进入数据库

当前运行中的轻量 Skill 位于 `skills/guided-chamber-reading/`。每间 chamber 的报告、
独立回答和 rebuttal 都只读取用户确认后的本室事实，不使用 JSON、Evidence ID 或 Rule ID
约束自然语言正文；人物口吻只能影响表达，不能补造盘面或确定性预测。

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
5. `POST /cases/{id}/debates` 执行固定一轮的独立回答、反驳和总结。
6. `GET /cases/{id}` 配合 `X-Case-Token` 恢复案件。

后端不会自行排盘。上传阶段，本地解析器先直接识别项目的结构化 TXT/JSON；其他
TXT/文本 PDF 由 DeepSeek 从临时文字中抽取显式事实，扫描件则先在本地运行 OCR。
原文件和完整文本不落盘。用户确认后，后端只把每间 chamber 的已确认事实、轻量
防幻觉契约与对应人物设定单独传给 DeepSeek。各室在报告阶段彼此隔离；只有 rebuttal
阶段会看到其他体系的第一轮回答，而且这些回答只能作为待回应证词，不能当作本室盘面事实。

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
网站不提供也不保存姓名、生日、出生时间、地点与时区字段；需要的资料应包含在上传报告中。

> 命理输出仅供反思与娱乐，不应用于医疗、法律、财务或其他重大决定。
