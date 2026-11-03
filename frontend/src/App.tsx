import { FormEvent, useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { createHelpRequest, getHelpRequest, itemTypes, type HelpRequest, type ItemType } from "./api";

function RequestFormPage() {
  const navigate = useNavigate();
  const [itemType, setItemType] = useState<ItemType>("scientific_calculator");
  const [location, setLocation] = useState("");
  const [deadline, setDeadline] = useState("");
  const [description, setDescription] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      const created = await createHelpRequest({
        item_type: itemType,
        location,
        deadline: new Date(deadline).toISOString(),
        raw_text: description,
      });
      navigate(`/requests/${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建请求失败，请重试。");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="shell">
      <div className="eyebrow">CAMPUSHANDS · MILESTONE 01</div>
      <h1>创建借物请求</h1>
      <p className="lead">以 Alice 的演示身份填写需求。保存后可以随时通过请求链接重新查看。</p>
      <div className="notice">演示模式 · 当前仅保存草稿，暂不联系帮助者。</div>
      <form onSubmit={submit} className="card">
        <label htmlFor="item-type">需要借什么？</label>
        <select id="item-type" value={itemType} onChange={(event) => setItemType(event.target.value as ItemType)}>
          {Object.entries(itemTypes).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
        </select>

        <label htmlFor="location">交接地点</label>
        <input id="location" value={location} onChange={(event) => setLocation(event.target.value)} maxLength={80} placeholder="例如 VA" required />

        <label htmlFor="deadline">最晚需要时间</label>
        <input id="deadline" type="datetime-local" value={deadline} onChange={(event) => setDeadline(event.target.value)} required />

        <label htmlFor="description">补充说明（可选）</label>
        <textarea id="description" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={1000} rows={4} placeholder="例如：20 分钟后要考试" />

        {error && <p role="alert" className="error">{error}</p>}
        <button type="submit" disabled={pending}>{pending ? "正在保存…" : "保存请求"}</button>
      </form>
    </main>
  );
}

function RequestDetailPage() {
  const { id } = useParams();
  const [request, setRequest] = useState<HelpRequest | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    if (!id) return;
    getHelpRequest(id)
      .then((result) => { if (active) setRequest(result); })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : "读取失败"); });
    return () => { active = false; };
  }, [id]);

  return (
    <main className="shell">
      <div className="eyebrow">CAMPUSHANDS · REQUEST #{id}</div>
      <h1>请求详情</h1>
      {error && <p role="alert" className="error card">{error}</p>}
      {!request && !error && <p role="status">正在读取请求…</p>}
      {request && <section className="card" aria-label="请求信息">
        <div className="status">状态：草稿（{request.status}）</div>
        <dl>
          <dt>物品</dt><dd>{itemTypes[request.item_type]}</dd>
          <dt>地点</dt><dd>{request.location}</dd>
          <dt>最晚需要时间</dt><dd>{new Date(request.deadline).toLocaleString()}</dd>
          {request.raw_text && <><dt>补充说明</dt><dd>{request.raw_text}</dd></>}
        </dl>
        <p className="subtle">已保存于数据库。此阶段尚未开始匹配或发送邀请。</p>
      </section>}
      <Link className="back" to="/">创建另一条请求</Link>
    </main>
  );
}

export default function App() {
  return <Routes>
    <Route path="/" element={<RequestFormPage />} />
    <Route path="/requests/:id" element={<RequestDetailPage />} />
    <Route path="*" element={<main className="shell"><h1>页面不存在</h1><Link to="/">返回首页</Link></main>} />
  </Routes>;
}
