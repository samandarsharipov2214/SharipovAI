'use client';

import Image from 'next/image';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  Bell,
  Bot,
  BrainCircuit,
  CandlestickChart,
  CircleDollarSign,
  LayoutDashboard,
  MessageSquareText,
  Newspaper,
  PieChart,
  Power,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  WalletCards,
} from 'lucide-react';

type Json = Record<string, unknown>;
type Section = 'Обзор'|'Рынок'|'AI-решение'|'Портфель'|'Сделки'|'AI-боты'|'AI-чат'|'Новости'|'Risk Center'|'Bybit'|'Настройки';

const NAV: Array<[Section, React.ComponentType<{size?: number}>]> = [
  ['Обзор', LayoutDashboard], ['Рынок', CandlestickChart], ['AI-решение', BrainCircuit],
  ['Портфель', PieChart], ['Сделки', CircleDollarSign], ['AI-боты', Bot],
  ['AI-чат', MessageSquareText], ['Новости', Newspaper], ['Risk Center', ShieldCheck],
  ['Bybit', WalletCards], ['Настройки', Settings],
];

function apiUrl(path: string) {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, '') ?? '';
  return `${base}${path}`;
}

function finiteNumber(value: unknown): number | null {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatUsdt(value: number | null): string {
  if (value === null) return '—';
  return `${value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`;
}

function Metric({label,value,note,kind=''}:{label:string;value:string;note:string;kind?:string}) {
  return <article className="metric"><span>{label}</span><strong className={kind}>{value}</strong><em>{note}</em></article>;
}

function EmptyEvidence({title}:{title:string}) {
  return <article className="panel"><h2>{title}</h2><p>Нет подтверждённых данных API. Интерфейс не подставляет демонстрационные значения.</p></article>;
}

export default function Home() {
  const [active, setActive] = useState<Section>('Обзор');
  const [health, setHealth] = useState<Json | null>(null);
  const [account, setAccount] = useState<Json | null>(null);
  const [bots, setBots] = useState<Json | null>(null);
  const [news, setNews] = useState<Json | null>(null);
  const [error, setError] = useState('');
  const [chat, setChat] = useState<Array<{from:'user'|'ai'; text:string}>>([
    { from:'ai', text:'Я онлайн. Могу объяснить доступные подтверждённые данные и состояние системы.' }
  ]);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    setError('');
    const results = await Promise.allSettled([
      fetch(apiUrl('/api/health')).then(r => r.ok ? r.json() : Promise.reject(new Error(`health ${r.status}`))),
      fetch(apiUrl('/api/exchange/account/snapshot')).then(r => r.ok ? r.json() : Promise.reject(new Error(`account ${r.status}`))),
      fetch(apiUrl('/api/ai-bots')).then(r => r.ok ? r.json() : Promise.reject(new Error(`bots ${r.status}`))),
      fetch(apiUrl('/api/social-news')).then(r => r.ok ? r.json() : Promise.reject(new Error(`news ${r.status}`))),
    ]);
    setHealth(results[0].status === 'fulfilled' ? results[0].value as Json : null);
    setAccount(results[1].status === 'fulfilled' ? results[1].value as Json : null);
    setBots(results[2].status === 'fulfilled' ? results[2].value as Json : null);
    setNews(results[3].status === 'fulfilled' ? results[3].value as Json : null);
    if (results.every(x => x.status === 'rejected')) setError('Backend временно недоступен');
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const equity = useMemo(() => finiteNumber(account?.total_equity), [account]);
  const available = finiteNumber(account?.total_available_balance);
  const positions = Array.isArray(account?.positions) ? account.positions.length : null;
  const summary = (bots?.summary ?? {}) as Json;
  const activeBots = finiteNumber(summary.active);
  const totalBots = finiteNumber(summary.total_bots);
  const botRows = Array.isArray(bots?.bots) ? bots.bots as Json[] : [];
  const newsRows = Array.isArray(news?.news) ? news.news as Json[] : [];
  const healthState = String(health?.status ?? health?.state ?? '').trim();

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    const text = message.trim();
    if (!text) return;
    setChat(v => [...v, { from:'user', text }]);
    setMessage('');
    try {
      const r = await fetch(apiUrl('/api/chat/message'), {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:text})
      });
      const out = await r.json() as Json;
      setChat(v => [...v, { from:'ai', text:String(out.reply ?? 'Ответ не получен') }]);
    } catch {
      setChat(v => [...v, { from:'ai', text:'Не удалось связаться с AI API.' }]);
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => setActive('Обзор')} aria-label="SharipoAI">
          <Image src="/sharipoai-logo.svg" alt="SharipoAI" width={174} height={88} priority />
        </button>
        <nav>{NAV.map(([label, Icon]) => <button key={label} className={active === label ? 'active' : ''} onClick={() => setActive(label)}><Icon size={18}/><span>{label}</span></button>)}</nav>
        <div className="aiMode"><div><Activity size={18}/><span><b>AI-режим</b><small>СТАТУС ИЗ API</small></span></div><button><Power size={17}/> Управление</button></div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="welcome"><p>Привет! 👋</p><span>Показываются только подтверждённые данные API</span></div>
          <div className="topStatus">
            <div><small>Статус системы</small><b>{healthState || 'Не подтверждён'}</b></div>
            <div><small>Подключение</small><b className={account ? 'ok' : ''}>{account ? 'Bybit подтверждён API' : 'Не подтверждено'}</b></div>
          </div>
          <div className="topIcons"><button aria-label="Поиск"><Search size={20}/></button><button aria-label="Уведомления"><Bell size={20}/></button><button aria-label="Обновить" onClick={() => void load()}><RefreshCw size={20}/></button></div>
        </header>

        {error && <div className="alert">{error}. Демонстрационные торговые значения не показываются.</div>}

        {active === 'Обзор' && <Overview equity={equity} available={available} positions={positions} activeBots={activeBots} totalBots={totalBots}/>} 
        {active === 'Рынок' && <EmptyEvidence title="Рынок"/>}
        {active === 'AI-решение' && <EmptyEvidence title="AI-решение"/>}
        {active === 'Портфель' && <PortfolioPage equity={equity} available={available} positions={positions}/>} 
        {active === 'Сделки' && <EmptyEvidence title="История сделок"/>}
        {active === 'AI-боты' && <BotsPage rows={botRows} active={activeBots} total={totalBots}/>} 
        {active === 'AI-чат' && <ChatPage chat={chat} message={message} setMessage={setMessage} send={sendMessage}/>} 
        {active === 'Новости' && <NewsPage rows={newsRows}/>} 
        {active === 'Risk Center' && <EmptyEvidence title="Risk Center"/>}
        {active === 'Bybit' && <BybitPage account={account}/>} 
        {active === 'Настройки' && <SettingsPage/>}
      </section>
    </main>
  );
}

function Overview({equity,available,positions,activeBots,totalBots}:{equity:number|null;available:number|null;positions:number|null;activeBots:number|null;totalBots:number|null}) {
  return <>
    <section className="metrics">
      <Metric label="Общий баланс" value={formatUsdt(equity)} note={equity === null ? 'Нет данных API' : 'Account snapshot'}/>
      <Metric label="Доступно" value={formatUsdt(available)} note={available === null ? 'Нет данных API' : 'Account snapshot'}/>
      <Metric label="Открытые позиции" value={positions === null ? '—' : String(positions)} note={positions === null ? 'Нет данных API' : 'Account snapshot'}/>
      <Metric label="Активные AI" value={activeBots === null ? '—' : String(activeBots)} note={totalBots === null ? 'Всего не подтверждено' : `из ${totalBots}`}/>
    </section>
    <section className="dashboardGrid">
      <EmptyEvidence title="Рыночный график"/>
      <EmptyEvidence title="Последнее AI-решение"/>
      <EmptyEvidence title="Последние сделки"/>
      <EmptyEvidence title="Производительность системы"/>
    </section>
  </>;
}

function PortfolioPage({equity,available,positions}:{equity:number|null;available:number|null;positions:number|null}) {
  return <section className="metrics">
    <Metric label="Баланс" value={formatUsdt(equity)} note="Account snapshot"/>
    <Metric label="Доступно" value={formatUsdt(available)} note="Account snapshot"/>
    <Metric label="Позиции" value={positions === null ? '—' : String(positions)} note="Account snapshot"/>
  </section>;
}

function BotsPage({rows,active,total}:{rows:Json[];active:number|null;total:number|null}) {
  if (!rows.length) return <EmptyEvidence title="AI-боты"/>;
  return <>
    <section className="metrics">
      <Metric label="Всего AI" value={total === null ? '—' : String(total)} note="API summary"/>
      <Metric label="Активны" value={active === null ? '—' : String(active)} note="API summary"/>
    </section>
    <section className="botGrid">{rows.map((row, index) => {
      const name = String(row.name ?? row.id ?? '').trim() || `AI #${index + 1}`;
      const status = String(row.status ?? row.state ?? '').trim() || 'Статус не указан';
      const lastAction = String(row.last_action ?? '').trim();
      return <article className="panel botCard" key={`${name}-${index}`}><Bot/><h3>{name}</h3><span>{status}</span>{lastAction && <p>Последнее действие: {lastAction}</p>}</article>;
    })}</section>
  </>;
}

function ChatPage({chat,message,setMessage,send}:{chat:Array<{from:'user'|'ai';text:string}>;message:string;setMessage:(v:string)=>void;send:(e:React.FormEvent)=>void}) {
  return <article className="panel chatPage"><h2>Чат с SharipoAI</h2><div className="chatLog">{chat.map((m,i)=><div key={i} className={`bubble ${m.from}`}><b>{m.from==='ai'?'SharipoAI':'Пользователь'}</b><p>{m.text}</p></div>)}</div><form onSubmit={send}><textarea value={message} onChange={e=>setMessage(e.target.value)} placeholder="Напиши команду или вопрос…"/><button>Отправить</button></form></article>;
}

function NewsPage({rows}:{rows:Json[]}) {
  const list = rows.slice(0,8).map(x => ({
    title: String(x.title ?? x.headline ?? '').trim(),
    source: String(x.source ?? '').trim(),
    impact: String(x.ai_impact ?? x.impact ?? '').trim(),
  })).filter(x => x.title);
  if (!list.length) return <EmptyEvidence title="Нет подтверждённых новостей"/>;
  return <section className="newsGrid">{list.map((n,i)=><article className="panel newsCard" key={`${n.title}-${i}`}><Newspaper/><div><small>{n.source || 'Источник не указан'}</small><h3>{n.title}</h3>{n.impact && <p>AI влияние: {n.impact}</p>}</div></article>)}</section>;
}

function BybitPage({account}:{account:Json|null}) {
  const connected = Boolean(account);
  const equity = finiteNumber(account?.total_equity);
  const available = finiteNumber(account?.total_available_balance);
  const positions = Array.isArray(account?.positions) ? account.positions.length : null;
  return <section className="pageGrid">
    <article className="panel bybitHero"><h2>{connected?'Аккаунт подтверждён API':'Подключение не подтверждено'}</h2><div className="metrics embedded"><Metric label="Баланс" value={formatUsdt(equity)} note="Account snapshot"/><Metric label="Доступно" value={formatUsdt(available)} note="Account snapshot"/><Metric label="Позиции" value={positions === null ? '—' : String(positions)} note="Account snapshot"/></div></article>
    <article className="panel"><h2>Безопасность</h2><p>Интерфейс не делает выводов о разрешениях API-ключа без отдельного подтверждённого security endpoint.</p></article>
  </section>;
}

function SettingsPage() {
  return <section className="settingsGrid">{['Общие','Уведомления','Торговля','Безопасность','Интеграции','Внешний вид'].map(x=><article className="panel settingCard" key={x}><Settings/><div><h3>{x}</h3><p>Параметры SharipoAI</p></div><button>Открыть</button></article>)}</section>;
}
