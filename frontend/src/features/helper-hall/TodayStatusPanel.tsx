import { useEffect, useState, type FormEvent } from "react";

import {
  getCampusLocations,
  getDailyAvailability,
  getHelperProfile,
  saveDailyAvailability,
  saveHelperProfile,
} from "./api";
import type {
  CampusLocation,
  DailyAvailability,
  HelperProfile,
  ItemType,
  ProfileItem,
  ProfileService,
  ServiceCode,
} from "./types";
import "./helperHall.css";


const itemLabels: Record<ItemType, string> = {
  scientific_calculator: "科学计算器",
  charger: "充电器",
  adapter: "转接头",
  stationery: "文具",
  umbrella: "雨伞",
  other: "其他物品",
};

const serviceLabels: Record<ServiceCode, string> = {
  moving: "搬运",
  printing: "打印",
  tutoring: "课程答疑",
  other: "其他服务",
};

function localInput(value: string): string {
  const date = new Date(value);
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return shifted.toISOString().slice(0, 16);
}

function initialWindow() {
  const start = new Date();
  const end = new Date(start.getTime() + 60 * 60 * 1000);
  if (end.getDate() !== start.getDate()) end.setHours(23, 59, 0, 0);
  return { start: localInput(start.toISOString()), end: localInput(end.toISOString()) };
}

export function TodayStatusPanel({ actorId }: { actorId: number }) {
  const defaults = initialWindow();
  const [profile, setProfile] = useState<HelperProfile | null>(null);
  const [daily, setDaily] = useState<DailyAvailability | null>(null);
  const [locations, setLocations] = useState<CampusLocation[]>([]);
  const [items, setItems] = useState<ProfileItem[]>([]);
  const [services, setServices] = useState<ProfileService[]>([]);
  const [willing, setWilling] = useState(false);
  const [availableFrom, setAvailableFrom] = useState(defaults.start);
  const [availableUntil, setAvailableUntil] = useState(defaults.end);
  const [building, setBuilding] = useState("Z");
  const [acceptsUrgent, setAcceptsUrgent] = useState(false);
  const [selectedItems, setSelectedItems] = useState<number[]>([]);
  const [selectedServices, setSelectedServices] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let active = true;
    setError("");
    Promise.all([getHelperProfile(actorId), getDailyAvailability(actorId), getCampusLocations()])
      .then(([nextProfile, nextDaily, nextLocations]) => {
        if (!active) return;
        setProfile(nextProfile);
        setItems(nextProfile.items);
        setServices(nextProfile.services);
        setDaily(nextDaily);
        setLocations(nextLocations);
        if (nextDaily.availability) {
          setWilling(nextDaily.availability.willing);
          setAvailableFrom(localInput(nextDaily.availability.available_from));
          setAvailableUntil(localInput(nextDaily.availability.available_until));
          setBuilding(nextDaily.availability.campus_building);
          setAcceptsUrgent(nextDaily.availability.accepts_urgent);
          setSelectedItems(nextDaily.availability.item_ids);
          setSelectedServices(nextDaily.availability.service_ids);
        }
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "读取状态失败"); });
    return () => { active = false; };
  }, [actorId]);

  function updateItem(index: number, values: Partial<ProfileItem>) {
    setItems((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...values } : item));
  }

  function updateService(index: number, values: Partial<ProfileService>) {
    setServices((current) => current.map((service, serviceIndex) => serviceIndex === index ? { ...service, ...values } : service));
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      const saved = await saveHelperProfile(actorId, items, services);
      setProfile(saved);
      setItems(saved.items);
      setServices(saved.services);
      setNotice("长期物品与服务能力已保存。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存长期资料失败");
    } finally {
      setPending(false);
    }
  }

  async function saveToday(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      const saved = await saveDailyAvailability(actorId, {
        willing,
        available_from: new Date(availableFrom).toISOString(),
        available_until: new Date(availableUntil).toISOString(),
        campus_building: building,
        accepts_urgent: acceptsUrgent,
        item_ids: selectedItems,
        service_ids: selectedServices,
      });
      setDaily(saved);
      setNotice("今日状态已更新，将在今天结束后自动失效。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存今日状态失败");
    } finally {
      setPending(false);
    }
  }

  function toggle(values: number[], value: number, selected: boolean, apply: (next: number[]) => void) {
    apply(selected ? [...new Set([...values, value])] : values.filter((entry) => entry !== value));
  }

  if (!profile || !daily) return <section className="helper-panel helper-loading" aria-label="我的今日状态">正在读取 Helper 资料…</section>;

  return <section className="helper-panel" aria-label="我的今日状态">
    <header className="helper-panel__header">
      <div><span className="helper-kicker">SUPPLY PROFILE</span><h2>我的今日状态</h2></div>
      <span className="helper-date">{daily.local_date}</span>
    </header>
    <p className="helper-intro">长期资料只需偶尔维护；每天只更新愿意帮助、时间、楼栋和今天可提供的能力。</p>
    {error && <p role="alert" className="helper-alert helper-alert--error">{error}</p>}
    {notice && <p role="status" className="helper-alert helper-alert--success">{notice}</p>}

    <form className="helper-card" onSubmit={(event) => void saveProfile(event)}>
      <div className="helper-section-title"><h3>长期物品与服务</h3><span>不会每天重复填写</span></div>
      <div className="helper-stack">
        {items.map((item, index) => <div className="helper-capability-row" key={item.id ?? `new-item-${index}`}>
          <select aria-label={`物品类别 ${index + 1}`} value={item.item_type} onChange={(event) => updateItem(index, { item_type: event.target.value as ItemType })}>
            {Object.entries(itemLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <input aria-label={`物品名称 ${index + 1}`} value={item.item_name} maxLength={120} placeholder="物品名称" onChange={(event) => updateItem(index, { item_name: event.target.value })} required />
          <input aria-label={`品牌 ${index + 1}`} value={item.brand ?? ""} maxLength={80} placeholder="品牌" onChange={(event) => updateItem(index, { brand: event.target.value || null })} />
          <input aria-label={`型号 ${index + 1}`} value={item.model ?? ""} maxLength={80} placeholder="型号" onChange={(event) => updateItem(index, { model: event.target.value || null })} />
          <label className="helper-inline-check"><input type="checkbox" checked={item.active} onChange={(event) => updateItem(index, { active: event.target.checked })} />启用</label>
        </div>)}
        <button type="button" className="helper-secondary" onClick={() => setItems((current) => [...current, { item_type: "other", item_name: "", brand: null, model: null, active: true }])}>添加物品</button>
      </div>
      <div className="helper-stack">
        {services.map((service, index) => <div className="helper-capability-row helper-capability-row--service" key={service.id ?? `new-service-${index}`}>
          <select aria-label={`服务类别 ${index + 1}`} value={service.service_code} onChange={(event) => updateService(index, { service_code: event.target.value as ServiceCode })}>
            {Object.entries(serviceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <input aria-label={`服务名称 ${index + 1}`} value={service.service_name} maxLength={120} placeholder="服务名称" onChange={(event) => updateService(index, { service_name: event.target.value })} required />
          <label className="helper-inline-check"><input type="checkbox" checked={service.active} onChange={(event) => updateService(index, { active: event.target.checked })} />启用</label>
        </div>)}
        <button type="button" className="helper-secondary" onClick={() => setServices((current) => [...current, { service_code: "moving", service_name: "", active: true }])}>添加服务</button>
      </div>
      <button type="submit" disabled={pending}>保存长期资料</button>
    </form>

    <form className="helper-card helper-card--today" onSubmit={(event) => void saveToday(event)}>
      <div className="helper-section-title"><h3>今天可提供什么</h3><span>次日自动失效</span></div>
      <label className="helper-toggle"><input type="checkbox" checked={willing} onChange={(event) => setWilling(event.target.checked)} /><span>今天愿意提供帮助</span></label>
      <div className="helper-grid">
        <label>开始时间<input aria-label="可帮助开始时间" type="datetime-local" value={availableFrom} onChange={(event) => setAvailableFrom(event.target.value)} required /></label>
        <label>结束时间<input aria-label="可帮助结束时间" type="datetime-local" value={availableUntil} onChange={(event) => setAvailableUntil(event.target.value)} required /></label>
        <label>当前楼栋<select aria-label="当前楼栋" value={building} onChange={(event) => setBuilding(event.target.value)}>{locations.map((location) => <option value={location.code} key={location.code}>{location.label_zh} · {location.code}</option>)}</select></label>
      </div>
      <label className="helper-inline-check"><input type="checkbox" checked={acceptsUrgent} onChange={(event) => setAcceptsUrgent(event.target.checked)} />接受紧急请求</label>
      {(daily.suggested_item_ids.length > 0 || daily.suggested_service_ids.length > 0) && <button type="button" className="helper-secondary" onClick={() => {
        setSelectedItems(daily.suggested_item_ids);
        setSelectedServices(daily.suggested_service_ids);
      }}>沿用上次清单</button>}
      <fieldset><legend>今天愿意提供的物品</legend>{profile.items.filter((item) => item.active).map((item) => <label className="helper-choice" key={item.id}>
        <input type="checkbox" checked={selectedItems.includes(item.id)} onChange={(event) => toggle(selectedItems, item.id, event.target.checked, setSelectedItems)} />
        <span>{item.item_name}</span><small>{[item.brand, item.model].filter(Boolean).join(" ")}</small>
      </label>)}</fieldset>
      <fieldset><legend>今天愿意提供的服务</legend>{profile.services.filter((service) => service.active).map((service) => <label className="helper-choice" key={service.id}>
        <input type="checkbox" checked={selectedServices.includes(service.id)} onChange={(event) => toggle(selectedServices, service.id, event.target.checked, setSelectedServices)} />
        <span>{service.service_name}</span><small>{serviceLabels[service.service_code]}</small>
      </label>)}</fieldset>
      <button type="submit" disabled={pending}>保存今日状态</button>
    </form>
  </section>;
}
