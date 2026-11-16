import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import {
  acceptProposal, actOnBoardRequest, actOnOffer, actOnRequest, agentObserve, agentSearch, ApiError, claimBoardRequest, createHelpRequest,
  declineProposal,
  editHelpRequest, getDemoRoles, getHelpRequest, getHelperBoard, getHelperOffers, getLocations, itemTypes, substitutionPolicyLabels,
  type AgentRun, type BoardEntry, type CampusLocation, type DemoRole, type HelperBoard,
  type HelpOffer, type HelpRequest, type ItemType, type MatchingIssue, type RequestAction, type RequestCategory, type SubstitutionPolicy,
} from "./api";
import NaturalRequestFlow from "./NaturalRequestFlow";
import { useRealtimeSnapshot } from "./realtime";
import SystemStatus, { providerLabel } from "./SystemStatus";

const issueMessages: Record<MatchingIssue, string> = {
  unknown_location: "交接地点尚未收录，请更正地点后重试。",
  no_item_inventory: "当前还没有可认领的同类物品。你仍可发布请求，等待帮助者加入。",
  exact_preference_unavailable: "当前没有符合准确品牌或型号偏好的可行认领者。你仍可保持严格偏好并发布。",
  alternatives_available_needs_confirmation: "有符合时限的同类兼容选项。只有你明确同意后，持有兼容物品的帮助者才可以认领。",
  no_available_helper: "当前暂无符合条件的帮助者。发布后仍可等待新的参与者。",
  unreachable_before_deadline: "当前没有能按时到达的帮助者。你可以延长截止时间或更改交接地点，也可先发布请求。",
  candidate_exhausted: "这条旧请求已结束。你可以重新创建请求并发布到求助广场。",
};
const statusLabels: Record<HelpRequest["status"], string> = {
  draft: "草稿",
  searching: "处理中",
  awaiting_response: "已发布，等待帮助者认领",
  matched: "匹配成功",
  in_progress: "交接中",
  completed: "已完成",
  cancelled: "已取消",
  expired: "已过期",
  failed: "未找到帮助者",
};
const categoryLabels: Record<RequestCategory, string> = { borrow: "借用物品", service: "寻求服务" };
const urgencyLabels = { normal: "普通", high: "紧急" } as const;

function displayTime(value: string) {
  return new Date(value).toLocaleString();
}

function localDateTime(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function locationOptions(locations: CampusLocation[]) {
  return locations.map((place) => <option key={place.code} value={place.code} label={`${place.label_zh} · ${place.label_en}`} />);
}

function DemoRoleSwitcher({ actorId, roles, onChange }: { actorId: number; roles: DemoRole[]; onChange: (id: number) => void }) {
  return <div className="demo-bar">
    <strong>Demo Mode</strong>
    <label htmlFor="demo-role">当前角色</label>
    <select id="demo-role" value={actorId} onChange={(event) => onChange(Number(event.target.value))}>
      {roles.length === 0 && <option value={actorId}>正在加载角色…</option>}
      {roles.map((person) => <option key={person.id} value={person.id}>{person.display_name} · {person.role === "requester" ? "Requester" : "Helper"}</option>)}
    </select>
  </div>;
}

function RequestFormPage() {
  const navigate = useNavigate();
  const showStructuredDebugForm = import.meta.env.VITE_SHOW_STRUCTURED_DEBUG_FORM === "true";
  const [locations, setLocations] = useState<CampusLocation[]>([]);
  const [category, setCategory] = useState<RequestCategory>("borrow");
  const [needSummary, setNeedSummary] = useState("");
  const [itemType, setItemType] = useState<ItemType>("scientific_calculator");
  const [location, setLocation] = useState("");
  const [deadline, setDeadline] = useState("");
  const [description, setDescription] = useState("");
  const [urgency, setUrgency] = useState<"normal" | "high">("normal");
  const [preferredBrand, setPreferredBrand] = useState("");
  const [preferredModel, setPreferredModel] = useState("");
  const [substitutionPolicy, setSubstitutionPolicy] = useState<SubstitutionPolicy>("equivalent_ok");
  const policyTouched = useRef(false);
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getLocations().then((result) => { if (active && Array.isArray(result)) setLocations(result); }).catch(() => {});
    return () => { active = false; };
  }, []);

  function updatePreference(kind: "brand" | "model", value: string) {
    if (kind === "brand") setPreferredBrand(value);
    else setPreferredModel(value);
    if (!policyTouched.current) setSubstitutionPolicy(value.trim() || (kind === "brand" ? preferredModel : preferredBrand).trim() ? "ask_before_substitute" : "equivalent_ok");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingRef.current) return;
    pendingRef.current = true;
    setError("");
    setPending(true);
    try {
      const created = await createHelpRequest({
        category,
        need_summary: needSummary.trim(),
        item_type: category === "service" ? "other" : itemType,
        location,
        deadline: new Date(deadline).toISOString(),
        urgency,
        raw_text: description,
        preferred_brand: category === "borrow" ? preferredBrand.trim() || null : null,
        preferred_model: category === "borrow" ? preferredModel.trim() || null : null,
        substitution_policy: category === "borrow" ? substitutionPolicy : "equivalent_ok",
      });
      sessionStorage.setItem("lastRequestId", String(created.id));
      navigate(`/requests/${created.id}`);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.code === "unknown_location" ?
        issueMessages.unknown_location : cause instanceof Error ? cause.message : "创建请求失败，请重试。");
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }

  return <main className="shell">
    <div className="eyebrow">CAMPUSHANDS · BORROWLOOP</div>
    <h1>描述你的需求</h1>
    <p className="lead">以 Alice 的演示身份描述需求；确认解析结果后，发布到校园求助广场。</p>
    <NaturalRequestFlow locations={locations} />
    {showStructuredDebugForm && <>
      <h2>结构化表单 · Demo / 调试入口</h2>
      <form onSubmit={submit} className="card">
      <label htmlFor="request-category">需求类型</label>
      <select id="request-category" value={category} onChange={(event) => setCategory(event.target.value as RequestCategory)}>
        <option value="borrow">借用物品</option><option value="service">寻求服务</option>
      </select>
      <label htmlFor="need-summary">需求摘要</label>
      <input id="need-summary" value={needSummary} onChange={(event) => setNeedSummary(event.target.value)} maxLength={200} required />
      {category === "borrow" && <>
        <label htmlFor="item-type">需要借什么？</label>
        <select id="item-type" value={itemType} onChange={(event) => setItemType(event.target.value as ItemType)}>
          {Object.entries(itemTypes).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
        </select>
      </>}
      <label htmlFor="location">交接地点</label>
      <input id="location" list="request-locations" value={location} onChange={(event) => setLocation(event.target.value)} maxLength={80} placeholder="例如 Z、Z栋或 Library" required />
      <datalist id="request-locations">{locationOptions(locations)}</datalist>
      <p className="subtle">可输入建筑代码或常见中英文别名；地点未收录时会提示更正。</p>
      <label htmlFor="deadline">最晚需要时间</label>
      <input id="deadline" type="datetime-local" value={deadline} onChange={(event) => setDeadline(event.target.value)} required />
      {category === "borrow" && <>
        <label htmlFor="preferred-brand">优先品牌（可选）</label>
        <input id="preferred-brand" value={preferredBrand} onChange={(event) => updatePreference("brand", event.target.value)} maxLength={80} placeholder="例如 Casio" />
        <label htmlFor="preferred-model">优先型号（可选）</label>
        <input id="preferred-model" value={preferredModel} onChange={(event) => updatePreference("model", event.target.value)} maxLength={80} />
        <label htmlFor="substitution-policy">替代品规则</label>
        <select id="substitution-policy" value={substitutionPolicy} onChange={(event) => { policyTouched.current = true; setSubstitutionPolicy(event.target.value as SubstitutionPolicy); }}>
          {Object.entries(substitutionPolicyLabels).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
        </select>
        <p className="subtle">有品牌或型号偏好时，默认先征求你对替代品的同意。</p>
      </>}
      <label htmlFor="request-urgency">紧急程度</label>
      <select id="request-urgency" value={urgency} onChange={(event) => setUrgency(event.target.value as "normal" | "high")}><option value="normal">普通</option><option value="high">紧急</option></select>
      <label htmlFor="description">补充说明（可选）</label>
      <textarea id="description" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={1000} rows={4} placeholder="例如：20 分钟后要考试" />
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit" data-action="create" disabled={pending}>{pending ? "正在保存…" : "保存请求"}</button>
      </form>
    </>}
  </main>;
}

function RequestDetailPage() {
  const { id } = useParams();
  const [request, setRequest] = useState<HelpRequest | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const [agentOutcome, setAgentOutcome] = useState<AgentRun | null>(null);
  const [statusRefreshToken, setStatusRefreshToken] = useState(0);
  const [editing, setEditing] = useState(false);
  const [editLocation, setEditLocation] = useState("");
  const [editDeadline, setEditDeadline] = useState("");
  const [locations, setLocations] = useState<CampusLocation[]>([]);

  function beginAction(): boolean {
    if (pendingRef.current) return false;
    pendingRef.current = true;
    setPending(true);
    setError("");
    return true;
  }

  function endAction(refreshProvider = false) {
    pendingRef.current = false;
    setPending(false);
    if (refreshProvider) setStatusRefreshToken((value) => value + 1);
  }

  useEffect(() => {
    if (!id) return;
    sessionStorage.setItem("lastRequestId", id);
    setRequest(null);
    setAgentOutcome(null);
    setEditing(false);
  }, [id]);

  const realtime = useRealtimeSnapshot<HelpRequest>({
    kind: "request", id: id ? Number(id) : null, actorId: 1,
    load: () => getHelpRequest(id ?? ""),
    onSnapshot: (snapshot) => {
      const unique = new Map((snapshot.events ?? []).map((event) => [event.id, event]));
      setRequest({ ...snapshot, events: [...unique.values()].sort((left, right) => left.id - right.id) });
    },
    onError: setError,
    snapshotEventId: (snapshot) => Math.max(0, ...(snapshot.events ?? []).map((event) => event.id)),
  });

  async function action(kind: RequestAction) {
    if (!id || !beginAction()) return;
    try {
      realtime.applyAuthoritative(await actOnRequest(id, kind));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "操作失败，请重试");
    } finally {
      endAction();
    }
  }

  async function runAgent() {
    if (!id || !beginAction()) return;
    setAgentOutcome(null);
    try {
      const outcome = await agentSearch(id);
      setAgentOutcome(outcome);
      realtime.applyAuthoritative(await getHelpRequest(id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Agent 暂不可用，请重试。");
      void realtime.refresh();
    } finally { endAction(true); }
  }

  async function observeAgent() {
    if (!id || !beginAction()) return;
    setAgentOutcome(null);
    try {
      const outcome = await agentObserve(id);
      setAgentOutcome(outcome);
      realtime.applyAuthoritative(await getHelpRequest(id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Agent 暂不可用，请重试。"); }
    finally { endAction(true); }
  }

  function beginEdit() {
    if (!request) return;
    setEditLocation(request.location);
    setEditDeadline(localDateTime(request.deadline));
    setEditing(true);
    void getLocations().then((result) => { if (Array.isArray(result)) setLocations(result); }).catch(() => {});
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!id || !request) return;
    const edits: { location?: string; deadline?: string } = {};
    if (editLocation.trim() !== request.location) edits.location = editLocation.trim();
    // datetime-local has minute precision. Sending an unchanged value would
    // silently shorten a deadline that originally included seconds.
    if (editDeadline !== localDateTime(request.deadline)) edits.deadline = new Date(editDeadline).toISOString();
    if (!Object.keys(edits).length) { setEditing(false); return; }
    if (!beginAction()) return;
    try {
      const changed = await editHelpRequest(id, edits);
      realtime.applyAuthoritative(changed);
      setEditing(false);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.code === "unknown_location" ? issueMessages.unknown_location :
        cause instanceof Error ? cause.message : "修改失败，请重试。");
      void realtime.refresh();
    } finally { endAction(true); }
  }

  async function proposalAction(offerId: number, kind: "accept" | "decline") {
    if (!id || !beginAction()) return;
    try { realtime.applyAuthoritative(kind === "accept" ? await acceptProposal(offerId) : await declineProposal(offerId)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "处理替代方案失败，请重试。"); void realtime.refresh(); }
    finally { endAction(); }
  }

  const parsedByAgent = (request?.events ?? []).some((event) => event.event_type === "request_parsed");
  const issue = request?.matching_issue;
  const canEdit = request?.status === "draft";
  const canPublish = canEdit && issue !== "unknown_location";
  const canCancel = request && ["draft", "searching", "awaiting_response", "matched", "in_progress"].includes(request.status);

  return <main className="shell">
    <div className="eyebrow">CAMPUSHANDS · REQUEST #{id}</div>
    <h1>{request?.need_summary ?? "请求详情"}</h1>
    <SystemStatus refreshToken={statusRefreshToken} />
    <p className="connection-mode" aria-label="连接状态">{realtime.mode === "live" ? "实时连接" : "轮询模式 · 每 2 秒更新"}</p>
    {error && <p role="alert" className="error card">{error}</p>}
    {pending && <p role="status">正在处理，请稍候…</p>}
    {agentOutcome && <section className="card agent-outcome" aria-label="Agent 操作结果" role="status">
      <strong>本次 Agent 操作记录</strong>
      <p>当时结果：{agentOutcome.message}；当前阶段见下方请求状态。</p>
      <p>来源：{providerLabel(agentOutcome.provider)}{agentOutcome.fallback_active ? " · 本地备用" : ""}</p>
      <p>已验证并交给服务的工具：{agentOutcome.validated_actions?.length ? agentOutcome.validated_actions.join(" → ") : "无"}</p>
      <p>{agentOutcome.action_committed ? "服务已提交操作" : "未提交业务操作"}</p>
    </section>}
    {!request && !error && <p role="status">正在读取请求…</p>}
    {request && <>
      <section className="card" aria-label="请求信息">
        <div className="status">状态：{statusLabels[request.status]}（{request.status}）</div>
        <dl>
          <dt>需求类型</dt><dd>{categoryLabels[request.category]}</dd>
          <dt>需求摘要</dt><dd>{request.need_summary}</dd>
          {request.category === "borrow" && <>
            <dt>物品</dt><dd>{itemTypes[request.item_type]}</dd>
            {request.preferred_brand && <><dt>优先品牌</dt><dd>{request.preferred_brand}</dd></>}
            {request.preferred_model && <><dt>优先型号</dt><dd>{request.preferred_model}</dd></>}
            <dt>替代品规则</dt><dd>{substitutionPolicyLabels[request.substitution_policy ?? "equivalent_ok"]}</dd>
          </>}
          <dt>紧急程度</dt><dd>{urgencyLabels[request.urgency]}</dd>
          <dt>地点</dt><dd>{request.location}</dd>
          <dt>最晚需要时间</dt><dd>{displayTime(request.deadline)}</dd>
          {request.raw_text && <><dt>补充说明</dt><dd>{request.raw_text}</dd></>}
          {request.matched_helper && <><dt>帮助者</dt><dd>{request.matched_helper}</dd></>}
          {request.helper_note && <><dt>帮助说明</dt><dd>{request.helper_note}</dd></>}
          {request.handoff_location && <><dt>交接地点</dt><dd>{request.handoff_location}</dd></>}
        </dl>
        {issue && <div className="matching-issue" role="status" aria-label="匹配提示">
          <strong>匹配提示</strong>
          <p>{issueMessages[issue]}</p>
          <div className="actions">
            {(issue === "unknown_location" || issue === "unreachable_before_deadline") && canEdit &&
              <button type="button" data-action="edit-request" disabled={pending} onClick={beginEdit}>更正地点或截止时间</button>}
            {canCancel && <button type="button" className="secondary" data-action="cancel" disabled={pending} onClick={() => void action("cancel")}>结束请求</button>}
            <Link className="inline-link" to="/">重新创建请求</Link>
          </div>
        </div>}
        {(request.proposals ?? []).filter((proposal) => proposal.status === "proposed").map((proposal) =>
          <section className="proposal" aria-label={`替代方案 ${proposal.id}`} key={proposal.id}>
            <h2>{proposal.helper_name} 提出的替代方案</h2>
            {(proposal.offered_brand || proposal.offered_model) && <p>可提供：{[proposal.offered_brand, proposal.offered_model].filter(Boolean).join(" ")}</p>}
            {proposal.help_note && <p>帮助说明：{proposal.help_note}</p>}
            <div className="actions">
              <button type="button" disabled={pending} onClick={() => void proposalAction(proposal.id, "accept")}>接受替代方案</button>
              <button type="button" className="secondary" disabled={pending} onClick={() => void proposalAction(proposal.id, "decline")}>拒绝替代方案</button>
            </div>
          </section>)}
        {editing && <form className="edit-request" onSubmit={(event) => void saveEdit(event)}>
          <label htmlFor="edit-request-location">更改交接地点</label>
          <input id="edit-request-location" list="edit-request-locations" maxLength={80} value={editLocation} onChange={(event) => setEditLocation(event.target.value)} required />
          <datalist id="edit-request-locations">{locationOptions(locations)}</datalist>
          <label htmlFor="edit-request-deadline">延长截止时间</label>
          <input id="edit-request-deadline" type="datetime-local" value={editDeadline} onChange={(event) => setEditDeadline(event.target.value)} required />
          <div className="actions">
            <button type="submit" data-action="save-request-edit" disabled={pending}>保存修改</button>
            <button type="button" className="secondary" disabled={pending} onClick={() => setEditing(false)}>取消编辑</button>
          </div>
        </form>}
        <div className="actions">
          {canPublish && (parsedByAgent ?
            <button data-action="agent-publish" disabled={pending} onClick={() => void runAgent()}>Agent 发布请求</button> :
            <button data-action="publish" disabled={pending} onClick={() => void action("publish")}>发布到求助广场</button>)}
          {parsedByAgent && request.status !== "draft" &&
            <button className="secondary" data-action="agent-observe" disabled={pending} onClick={() => void observeAgent()}>Agent 查看下一步</button>}
          {request.status === "matched" && <button data-action="start" disabled={pending} onClick={() => void action("start")}>开始交接</button>}
          {request.status === "in_progress" && !request.requester_confirmed && <button data-action="complete" disabled={pending} onClick={() => void action("complete")}>确认完成</button>}
          {!issue && canCancel &&
            <button className="secondary" data-action="cancel" disabled={pending} onClick={() => void action("cancel")}>取消请求</button>}
        </div>
        {request.status === "awaiting_response" && <p className="published-message" role="status">请求已发布，正在等待校园内的帮助者响应。</p>}
        {request.status === "in_progress" && request.requester_confirmed && <p className="subtle">你已确认，等待帮助者确认。</p>}
      </section>
      <section className="card timeline" aria-label="公开操作时间线">
        <h2>操作时间线</h2>
        {(request.events ?? []).length === 0 ? <p className="subtle">尚无操作事件。</p> :
          <ol>{(request.events ?? []).map((event) => <li key={event.id}><span>{event.public_message}</span><time>{displayTime(event.created_at)}</time></li>)}</ol>}
      </section>
    </>}
    <Link className="back" to="/">创建另一条请求</Link>
  </main>;
}

function BoardRequestCard({ request, pending, onClaim, onDismiss }: {
  request: BoardEntry;
  pending: boolean;
  onClaim: (request: BoardEntry) => void;
  onDismiss: (request: BoardEntry) => void;
}) {
  return <article className="card board-request" aria-label={`求助 ${request.id}`}>
    <div className="status">{request.need_summary}</div>
    <dl>
      <dt>Requester</dt><dd>{request.requester_name}</dd>
      <dt>需求类型</dt><dd>{categoryLabels[request.category]}</dd>
      <dt>紧急程度</dt><dd>{urgencyLabels[request.urgency]}</dd>
      <dt>交接地点</dt><dd>{request.location}</dd>
      <dt>最晚需要时间</dt><dd>{displayTime(request.deadline)}</dd>
    </dl>
    <div className="actions">
      <button data-action="claim" disabled={pending} onClick={() => onClaim(request)}>我可以帮助</button>
      <button className="secondary" data-action="dismiss" disabled={pending} onClick={() => onDismiss(request)}>暂不参与</button>
    </div>
  </article>;
}

function HelperBoardPage({ actorId }: { actorId: number }) {
  const [board, setBoard] = useState<HelperBoard | null>(null);
  const [offers, setOffers] = useState<HelpOffer[]>([]);
  const [error, setError] = useState("");
  const [boardNotice, setBoardNotice] = useState("");
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<BoardEntry | null>(null);
  const [capabilityConfirmed, setCapabilityConfirmed] = useState(false);
  const [responseType, setResponseType] = useState<"direct" | "substitute">("direct");
  const [helpNote, setHelpNote] = useState("");
  const [offeredBrand, setOfferedBrand] = useState("");
  const [offeredModel, setOfferedModel] = useState("");
  const pendingRef = useRef(false);
  const hadSnapshot = useRef(false);
  const previousOpen = useRef<Set<number>>(new Set());
  const ownClaims = useRef<Set<number>>(new Set());

  const realtime = useRealtimeSnapshot<{ board: HelperBoard; offers: HelpOffer[] }>({
    kind: "helper_board", id: actorId === 1 ? null : actorId, actorId,
    load: async () => {
      const [freshBoard, freshOffers] = await Promise.all([getHelperBoard(actorId), getHelperOffers(actorId)]);
      return { board: freshBoard, offers: freshOffers };
    },
    onSnapshot: (snapshot) => {
      const claimedByMe = new Set(snapshot.offers.filter((offer) => offer.status === "accepted").map((offer) => offer.request_id));
      const closedByClaim = new Set(snapshot.board.closed_requests
        .filter((entry) => ["matched", "in_progress", "completed"].includes(entry.status)).map((entry) => entry.id));
      if (hadSnapshot.current && [...previousOpen.current].some((id) => closedByClaim.has(id) && !claimedByMe.has(id) && !ownClaims.current.has(id))) {
        setBoardNotice("该请求已被其他同学接下");
      }
      previousOpen.current = new Set(snapshot.board.requests.map((entry) => entry.id));
      hadSnapshot.current = true;
      setBoard(snapshot.board);
      setOffers(snapshot.offers);
    },
    onError: setError,
  });

  function openClaim(request: BoardEntry) {
    setSelectedRequest(request);
    setCapabilityConfirmed(false);
    setResponseType("direct");
    setHelpNote("");
    setOfferedBrand("");
    setOfferedModel("");
    setError("");
  }

  async function boardAction(request: BoardEntry, action: "dismiss" | "restore") {
    if (pendingRef.current) return;
    pendingRef.current = true;
    setPendingId(request.id);
    setError("");
    setBoardNotice("");
    try {
      await actOnBoardRequest(request.id, actorId, action);
      await realtime.refresh();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409 && cause.code === "already_claimed") {
        setBoardNotice("该请求已被其他同学接下");
        await realtime.refresh();
      } else {
        setError(cause instanceof Error ? cause.message : "操作失败，请重试。");
      }
    } finally {
      pendingRef.current = false;
      setPendingId(null);
    }
  }

  async function submitClaim(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRequest || !capabilityConfirmed || pendingRef.current) return;
    pendingRef.current = true;
    setPendingId(selectedRequest.id);
    setError("");
    setBoardNotice("");
    try {
      const offer = await claimBoardRequest(selectedRequest.id, actorId, {
        capability_confirmed: true,
        response_type: selectedRequest.category === "service" ? "direct" : responseType,
        help_note: helpNote.trim() || null,
        offered_brand: selectedRequest.category === "borrow" ? offeredBrand.trim() || null : null,
        offered_model: selectedRequest.category === "borrow" ? offeredModel.trim() || null : null,
      });
      if (offer.status === "accepted") ownClaims.current.add(selectedRequest.id);
      else if (offer.status === "proposed") setBoardNotice("替代方案已发送，等待 Requester 确认。");
      setSelectedRequest(null);
      await realtime.refresh();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409 && cause.code === "already_claimed") {
        setBoardNotice("该请求已被其他同学接下");
        setSelectedRequest(null);
        await realtime.refresh();
      } else {
        setError(cause instanceof Error ? cause.message : "响应失败，请重试。");
      }
    } finally {
      pendingRef.current = false;
      setPendingId(null);
    }
  }

  async function confirmOwnOffer(offer: HelpOffer) {
    if (pendingRef.current) return;
    pendingRef.current = true;
    setPendingId(offer.request_id);
    setError("");
    try {
      await actOnOffer(offer.id, actorId, "confirm-completion");
      await realtime.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "确认失败，请重试。");
    } finally {
      pendingRef.current = false;
      setPendingId(null);
    }
  }

  return <main className="shell">
    <div className="eyebrow">CAMPUSHANDS · HELPER BOARD</div>
    <h1>{board?.viewer.display_name ?? "Helper"} 的求助广场</h1>
    <p className="connection-mode" aria-label="连接状态">{realtime.mode === "live" ? "实时连接" : "轮询模式 · 每 2 秒更新"}</p>
    <p className="lead">校园内已发布的物品和服务请求会同时出现在各位 Helper 的广场，由你自行判断能否按时完成。</p>
    {error && <p role="alert" className="error card">{error}</p>}
    {boardNotice && <p role="status" className="board-notice">{boardNotice}</p>}
    {!board && !error && <p role="status" className="card">正在读取求助广场…</p>}
    {board && <>
      <section aria-label="开放请求" className="board-list">
        <h2>开放请求</h2>
        {board.requests.length === 0 ? <p className="card">当前没有开放请求。</p> :
          board.requests.map((entry) => <BoardRequestCard key={entry.id} request={entry} pending={pendingId !== null}
            onClaim={openClaim} onDismiss={(item) => void boardAction(item, "dismiss")} />)}
      </section>
      {board.dismissed_requests.length > 0 && <details className="card dismissed-list">
        <summary>已隐藏的请求（{board.dismissed_requests.length}）</summary>
        {board.dismissed_requests.map((entry) => <div key={entry.id} className="dismissed-request">
          <span>#{entry.id} · {entry.requester_name} · {entry.need_summary} · {entry.location}</span>
          <button className="secondary" data-action="restore" disabled={pendingId !== null} onClick={() => void boardAction(entry, "restore")}>恢复显示</button>
        </div>)}
      </details>}
      {selectedRequest && <section className="card claim-dialog" role="dialog" aria-modal="true" aria-label="确认响应">
        <h2>确认响应：{selectedRequest.need_summary}</h2>
        <p>{categoryLabels[selectedRequest.category]} · {selectedRequest.location} · {displayTime(selectedRequest.deadline)} · {urgencyLabels[selectedRequest.urgency]}</p>
        <form onSubmit={(event) => void submitClaim(event)}>
          <label className="checkbox-label" htmlFor="capability-confirmed">
            <input id="capability-confirmed" type="checkbox" checked={capabilityConfirmed} onChange={(event) => setCapabilityConfirmed(event.target.checked)} />
            我确认自己能够在截止时间前完成该请求
          </label>
          <label htmlFor="help-note">帮助说明（可选）</label>
          <textarea id="help-note" value={helpNote} onChange={(event) => setHelpNote(event.target.value)} maxLength={300} rows={3} />
          {selectedRequest.category === "borrow" && <>
            <label htmlFor="response-type">响应方式</label>
            <select id="response-type" value={responseType} onChange={(event) => setResponseType(event.target.value as "direct" | "substitute")}>
              <option value="direct">直接满足需求</option><option value="substitute">提出替代物品</option>
            </select>
            <label htmlFor="offered-brand">实际提供品牌（可选）</label>
            <input id="offered-brand" value={offeredBrand} onChange={(event) => setOfferedBrand(event.target.value)} maxLength={80} />
            <label htmlFor="offered-model">实际提供型号（可选）</label>
            <input id="offered-model" value={offeredModel} onChange={(event) => setOfferedModel(event.target.value)} maxLength={80} />
          </>}
          <div className="actions">
            <button type="submit" disabled={pendingId !== null || !capabilityConfirmed}>确认响应</button>
            <button type="button" className="secondary" disabled={pendingId !== null} onClick={() => setSelectedRequest(null)}>返回</button>
          </div>
        </form>
      </section>}
      {offers.filter((offer) => offer.status === "proposed").map((offer) => <section className="card proposal" key={offer.id} aria-label={`我的替代方案 ${offer.request_id}`}>
        <h2>替代方案等待确认</h2>
        <p>{offer.need_summary}</p>
        {(offer.offered_brand || offer.offered_model) && <p>你提出：{[offer.offered_brand, offer.offered_model].filter(Boolean).join(" ")}</p>}
      </section>)}
      {offers.filter((offer) => offer.status === "accepted").map((offer) => <section className="card own-claim" key={offer.id} aria-label={`我的认领 ${offer.request_id}`}>
        <h2>我已接下的请求</h2>
        <p>{offer.need_summary} · 交接地点 {offer.location}</p>
        {offer.help_note && <p>帮助说明：{offer.help_note}</p>}
        <p>状态：{statusLabels[offer.request_status]}</p>
        {offer.request_status === "in_progress" && !offer.helper_confirmed &&
          <button data-action="confirm-completion" disabled={pendingId !== null} onClick={() => void confirmOwnOffer(offer)}>确认交接完成</button>}
      </section>)}
    </>}
  </main>;
}

export default function App() {
  const navigate = useNavigate();
  const [actorId, setActorId] = useState(() => Number(sessionStorage.getItem("demoActorId")) || 1);
  const [roles, setRoles] = useState<DemoRole[]>([]);

  useEffect(() => {
    let active = true;
    getDemoRoles().then((result) => { if (active && Array.isArray(result)) setRoles(result); }).catch(() => {});
    return () => { active = false; };
  }, []);

  function switchRole(id: number) {
    setActorId(id);
    sessionStorage.setItem("demoActorId", String(id));
    const lastRequestId = sessionStorage.getItem("lastRequestId");
    navigate(id === 1 ? (lastRequestId ? `/requests/${lastRequestId}` : "/") : "/helper-board");
  }

  return <>
    <DemoRoleSwitcher actorId={actorId} roles={roles} onChange={switchRole} />
    <Routes>
      <Route path="/" element={actorId === 1 ? <RequestFormPage /> : <HelperBoardPage key={actorId} actorId={actorId} />} />
      <Route path="/requests/:id" element={actorId === 1 ? <RequestDetailPage /> : <HelperBoardPage key={actorId} actorId={actorId} />} />
      <Route path="/helper-board" element={actorId === 1 ? <main className="shell"><p>请选择 Helper 角色查看求助广场。</p></main> : <HelperBoardPage key={actorId} actorId={actorId} />} />
      <Route path="/helpers/:id/offers" element={actorId === 1 ? <main className="shell"><p>请选择 Helper 角色查看求助广场。</p></main> : <HelperBoardPage key={actorId} actorId={actorId} />} />
      <Route path="*" element={<main className="shell"><h1>页面不存在</h1><Link to="/">返回首页</Link></main>} />
    </Routes>
  </>;
}
