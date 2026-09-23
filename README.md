# The Castle of Crossed Destinies

一个让七种象征体系独立阅读、彼此回应的案件工作台：八字、紫微斗数、西占、印占、数秘、人类图与 Dreamspell。现在可输入一次出生资料，在本地计算七套核心盘面；原来的七体系报告上传入口仍然保留。确认盘面后，所选 Chamber 独立生成证词。

## 包含内容

- 三种 AI 入口：自带 Key、Castle 案卷额度、两间密室体验；默认仅开放 BYOK，平台预算为零
- 后台任务逐篇保存、进度轮询、重启后继续失败步骤、相同请求去重
- 账户／额度流水／API token 与成本估算；免费与付费全站预算默认 0
- 免费虚构示范庭审；测试收银台与真实调用额度隔离，真实收款暂未启用
- [额度、任务与支付测试说明](docs/BILLING-AND-JOBS.md)

- 自动排盘：出生公历日期、准确钟表时间、城市；紫微另需传统性别参数。只选数秘 / Dreamspell 时无需时间和城市
- 离线 GeoNames 城市搜索、固定版本 IANA 历史时区 / 夏令时解析
- 八字：四柱、藏干、十神；紫微：十二宫、星曜、生年四化；西占：十天体、ASC/MC、整宫宫位、主要相位
- 印占：Lahiri 近似式、D1 / D9 星座、宿 / 足、Vimshottari 大运；Human Design：太阳弧 88°回溯、26 个激活、类型 / 权威 / 人生角色 / 定义 / 通道
- 数秘：日期数，选填 A–Z 姓名后增加姓名数，明确 Y 与主数约定；Dreamspell：Kin、调性、图腾、波符位置，闰日要求用户选择
- 真太阳时和 23:00 / 00:00 换日可选；排盘约定和引擎版本随案件保存、恢复、导出
- 自动排盘不使用 AI 或收费排盘 API；DeepSeek 只在用户确认后进行解读
- 每套体系分别上传 PDF、TXT/MD、PNG/JPG/WEBP/TIFF
- 文本 PDF 直接读取；扫描 PDF 与图片使用 Tesseract OCR
- 项目使用的六份 AI-readable TXT/JSON 由本地确定性解析器直接读取，不让模型猜字段；
  西占和印占优先保留核心盘面、分盘与时限层，最多 80 条事实
- DeepSeek 从本地取得的临时文字中只抽取显式盘面事实，并隔离原报告中的解释性文字
- 用户逐条修改、删除、补充和确认抽取事实
- 单一轻量流程：每室的人物性格＋紧凑防幻觉契约＋自然语言长文
- 原七套完整知识包保留在 `skills/*-chamber/` 作为归档资料，不进入当前运行路径
- 姓名不必填，仅数秘提供可选拼写输入；文档上传模式仍无需填写出生资料
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

需要 Python 3.12+、Node.js 22+。首次先安装本地计算引擎（在项目根目录运行）：

```bash
npm ci --prefix engines --ignore-scripts
```

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

仓库包含 `compose.yml`、`Caddyfile` 和两个 Dockerfile。API 镜像自动安装 Node 排盘依赖，复制 `engines/` 到 `/engines`、`skills/` 到 `/skills`；无需单独部署 Node 服务，也不新增对外端口。

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

1. 自动排盘：`GET /locations?q=北京` 搜索城市；`POST /cases/calculate` 校验时间、计算盘面并建立案件（不需要 API Key）。文档上传：`POST /cases` 建立空案件。服务端只保存恢复令牌的 SHA-256 哈希。
2. `POST /cases/{id}/sources/{system}` 临时读取文件并抽取事实；原始文件不落盘。
3. `PUT /cases/{id}/facts/{system}` 保存用户确认后的事实及必要的短原文定位。
4. `POST /cases/{id}/reports` 返回 202 任务，独立报告完成即保存，再召开 Tribunal。
5. `POST /cases/{id}/debates` 返回 202 任务，逐步保存独立回答、反驳和总结。
6. `GET /cases/{id}` 配合 `X-Case-Token` 恢复案件。
7. `POST /cases/{id}/jobs/{job_id}/retry` 继续未完成步骤；`DELETE /cases/{id}` 永久删除案卷内容。

API Key 留空不再自动使用服务器 Key。必须明确选择 Castle 额度并登录，且运营者已设置预算。
服务器仅运行一个 API worker。详见上方额度文档；实际售价与订阅暂不启用。

自动排盘在服务器本地运行确定性引擎，计算结果直接成为可确认事实，不经过 AI 抽取。
上传阶段，本地解析器先直接识别项目的结构化 TXT/JSON；其他
TXT/文本 PDF 由 DeepSeek 从临时文字中抽取显式事实，扫描件则先在本地运行 OCR。
原文件和完整文本不落盘。用户确认后，后端只把每间 chamber 的已确认事实、轻量
防幻觉契约与对应人物设定单独传给 DeepSeek。各室在报告阶段彼此隔离；只有 rebuttal
阶段会看到其他体系的第一轮回答，而且这些回答只能作为待回应证词，不能当作本室盘面事实。

上传限制为每份 15 MB。本地 PDF 最多处理前 40 页。数据库会保存用户确认后的事实、证词、
Tribunal 和辩论记录；自动排盘案件还保存出生资料、城市坐标、时区、UTC 瞬间和计算约定。
不会保存原始 PDF/图片、完整 OCR 文本或 API Key。案卷与 Markdown 导出可能包含敏感出生资料，请妥善保管。

## 配置 DeepSeek

支持两种方式：

1. **访客 BYOK**：在页面上方的访问方式面板输入 Key。Key 只保存在当前页面内存，通过
   `X-DeepSeek-Key` 发送给后端后立即转发；不写入 localStorage、数据库或日志。
2. **Castle 额度**：复制并填写仅存放在服务器上的环境文件。需要用户账户、可用点数和运营者已设置的预算，不是留空 Key 的自动回退：

```bash
cp backend/.env.example backend/.env
```

```env
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_MODEL=deepseek-flash
CASTLE_FREE_BUDGET_USD=0
CASTLE_PAID_BUDGET_USD=0
```

`DEEPSEEK_API_KEY` 仅由后端读取，绝不能放入前端代码或 Git。
公网 HTTPS 仍是正式部署的强烈建议。为方便初次在 VPS IP 上测试，页面不会阻止
HTTP 下填写 BYOK，但会显示明文传输风险警告；此时请只使用可随时撤销的测试 Key。
不愿提供出生资料时，可以使用原来的文档上传入口。

## 计算边界与验证

详见 [排盘约定](docs/CALCULATION-ENGINES.md) 和 [第三方来源](THIRD_PARTY_NOTICES.md)。
自动排盘支持 1900–2099 年，七套均已接通核心计算，但不等于每种流派、所有细分项目均已实现。
八字暂不输出大运/起运日期；紫微暂不输出运限/飞化；西占仅整宫制，不计算月交点、推运或行运。
印占近似岁差不能保证与 Swiss Ephemeris / Jagannatha Hora 逐位一致，大运日期也可能有数日差异；不输出下级大运。
Human Design 不输出 color/tone/base、四箭头或未经核验的轮回交叉名称。
数秘不自动翻译姓名或猜拼音；Dreamspell 不冒充传统 Maya 历法。
出生时间不详时不应填假时间；可只选日期型体系，或上传已有报告。

在项目根目录运行测试：

```bash
npm test --prefix engines
backend/.venv/bin/python -m unittest discover -s backend/tests -v
npm run build --prefix frontend
```

后端找不到 Node 时可配置 `CASTLE_NODE_BIN=/absolute/path/to/node`。

> 命理输出仅供反思与娱乐，不应用于医疗、法律、财务或其他重大决定。
