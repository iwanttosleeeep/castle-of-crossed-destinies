# The Castle of Crossed Destinies

一个将可自动化命理 API 置于同一审计框架的 MVP。

## 包含内容

- 出生资料表单、时间精度披露与报告状态流
- 可替换的 Western / Jyotish / BaZi / Human Design provider 层
- 统一 `CanonicalChart → Claim → Tribunal` 数据流
- 共识、冲突、交叉质询、Barnum 风险与证据可追溯性界面
- 未配置供应商密钥时的显式演示模式；不会伪装成真实计算结果

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

## 连接真实 provider

复制 `backend/.env.example` 为 `.env` 并填写端点与密钥。每个 provider 被隔离在 `backend/app/providers.py`，替换供应商时只需新增 adapter；业务和审计逻辑不依赖某一家 API。

> 命理输出仅供反思与娱乐，不应用于医疗、法律、财务或其他重大决定。
