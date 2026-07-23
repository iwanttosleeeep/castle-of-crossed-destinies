# The Castle of Crossed Destinies

一个将七套本地命理 Skill 置于同一审计框架的 MVP：八字、紫微斗数、西占、印占、数秘、人类图与 Dreamspell。

## 包含内容

- 出生资料表单、时间精度披露与报告状态流
- 七个项目内、版本可控的 Chamber Skills：`skills/*-chamber/`
- 手动导入的盘面事实 → Skill 证词 → Tribunal 审计数据流
- 共识、冲突、交叉质询、Barnum 风险与证据可追溯性界面
- 不调用外部 API；没有可核验盘面事实时，不生成解释性结论

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

## 输入盘面事实

在界面的「事实档案」中每行使用 `system | label | value`：

```text
bazi | Day Master | 甲木
ziwei | 命宫主星 | 紫微、天府
western | Mercury | 9th house
```

后端只接纳这些用户提供的事实，不会自行排盘或请求第三方服务。随后用相应的 `skills/<system>-chamber` 对事实进行解释，所有 claim 都必须回指事实 ID。

> 命理输出仅供反思与娱乐，不应用于医疗、法律、财务或其他重大决定。
