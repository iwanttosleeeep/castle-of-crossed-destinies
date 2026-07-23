# The Castle of Crossed Destinies

一个将七套本地命理 Skill 置于同一审计框架的 MVP：八字、紫微斗数、西占、印占、数秘、人类图与 Dreamspell。可选地使用 DeepSeek 生成受 Skill 约束的结构化证词。

## 包含内容

- 出生资料表单、时间精度披露与报告状态流
- 七个项目内、版本可控的 Chamber Skills：`skills/*-chamber/`
- 共享证据契约、受控主题词表、每套体系独立知识边界与来源
- 中性证词与人物语气分两次生成；Tribunal 只读取中性证词
- 手动导入的盘面事实 → Skill 证词 → Tribunal 审计数据流
- 共识、冲突、交叉质询、Barnum 风险与证据可追溯性界面
- 没有可核验盘面事实时，不生成解释性结论

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

## 输入盘面事实

在界面的「事实档案」中每行使用 `system | label | value`：

```text
bazi | Day Master | 甲木
ziwei | 命宫主星 | 紫微、天府
western | Mercury | 9th house
```

后端不会自行排盘。随后它会把每间 chamber 的事实、共享证据契约、
`SKILL.md` 与 `references/knowledge.md` 单独传给 DeepSeek；所有 claim 都必须
同时回指事实 ID 与知识包中的规则 ID。第一遍只生成中性证词，第二遍只根据
`references/persona.md` 改写语气。Tribunal 应始终使用 `neutral_statement`，
而不是人物化后的 `statement`。未配置 Key 时，事实仍可预览，但不会生成解释。

## 配置 DeepSeek

支持两种方式：

1. **访客 BYOK**：在首页输入 Key。Key 只保存在当前页面内存，经 HTTPS
   通过 `X-DeepSeek-Key` 发送给后端后立即转发；不写入 localStorage、数据库或日志。
2. **自托管默认 Key**：复制并填写仅存放在服务器上的环境文件：

```bash
cp backend/.env.example backend/.env
```

```env
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_MODEL=deepseek-v4-flash
```

`DEEPSEEK_API_KEY` 仅由后端读取，绝不能放入前端代码或 Git。
通过公网使用 BYOK 必须启用 HTTPS；HTTP 部署只应使用服务器端 `.env`。

> 命理输出仅供反思与娱乐，不应用于医疗、法律、财务或其他重大决定。
