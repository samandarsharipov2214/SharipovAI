'use client';

import Image from 'next/image';
import { useEffect, useMemo, useState } from 'react';
import {
  Activity, Bot, BrainCircuit, CandlestickChart, CircleDollarSign, LayoutDashboard,
  MessageSquareText, Newspaper, PieChart, Settings, ShieldCheck, WalletCards,
  Search, Bell, Power, RefreshCw, ArrowUpRight
} from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Pie, PieChart as RePieChart, Cell } from 'recharts';

type Json = Record<string, unknown>;
type Section = 'Обзор'|'Рынок'|'AI-решение'|'Портфель'|'Сделки'|'AI-боты'|'AI-чат'|'Новости'|'Risk Center'|'Bybit'|'Настройки';

const NAV: Array<[Section, React.ComponentType<{size?: number}>]> = [
  ['Обзор', LayoutDashboard], ['Рынок', CandlestickChart], ['AI-решение', BrainCircuit],
  ['Портфель', PieChart], ['Сделки', CircleDollarSign], ['AI-боты', Bot],
  ['AI-чат', MessageSquareText], ['Новости', Newspaper], ['Risk Center', ShieldCheck],
  ['Bybit', WalletCards], ['Настройки', Settings],
];

const portfolioSeries = [
  { t: '09:00', v: 22140 }, { t: '10:00', v: 22260 }, { t: '11:00', v: 22190 },
  { t: '12:00', v: 22420 }, { t: '13:00', v: 22370 }, { t: '14:00', v: 22610 },
  { t: '15:00', v: 22545 }, { t: '16:00', v: 22790 }, { t: '17:00', v: 22940 },
];

const market = [
  ['BTC/USDT','118 432.45','+1.24%'],['ETH/USDT','2 987.31','+2.15%'],
  ['SOL/USDT','167.45','-0.21%'],['BNB/USDT','693.22','+0.73%'],
  ['XRP/USDT','0.5632','+1.42%'],['ADA/USDT','0.4121','+0.92%'],
];

const allocation = [
  { name:'USDT', value:40.2, color:'#2a9df4' }, { name:'BTC', value:30.1, color:'#f59e0b' },
  { name:'ETH', value:15.4, color:'#7c3aed' }, { name:'SOL', value:8.7, color:'#06b6d4' },
  { name:'Другое', value:5.6, color:'#334155' },
];

function apiUrl(path: string) {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, '') ?? '';
  return `${base}${path}`;
}

function asNumber(v: unknown, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export default function Home() {
  const [active, setActive] = useState<Section>('Обзор');
  const [health, setHealth] = useState<Json | null>(null);
  const [account, setAccount] = useState<Json | null>(null);
  const [bots, setBots] = useState<Json | null>(null);
  const [news, setNews] = useState<Json | null>(null);
  const [error, setError] = useState('');
  const [chat, setChat] = useState<Array<{from:'user'|'ai'; text:string}>>([
    { from:'ai', text:'Я онлайн. Могу объяснить решение, проверить риск, портфель, рынок и состояние Bybit.' }
  ]);
  const [message, setMessage] = useState('');

  const load = async () => {
    setError('');
    const results = await Promise.allSettled([
      fetch(apiUrl('/api/health')).then(r => r.ok ? r.json() : Promise.reject(new Error(`health ${r.status}`))),
      fetch(apiUrl('/api/exchange/account/snapshot')).then(r => r.ok ? r.json() : Promise.reject(new Error(`account ${r.status}`))),
      fetch(apiUrl('/api/ai-bots')).then(r => r.ok ? r.json() : Promise.reject(new Error(`bots ${r.status}`))),
      fetch(apiUrl('/api/social-news')).then(r => r.ok ? r.json() : Promise.reject(new Error(`news ${r.status}`))),
    ]);
    if (results[0].status === 'fulfilled') setHealth(results[0].value as Json);
    if (results[1].status === 'fulfilled') setAccount(results[1].value as Json);
    if (results[2].status === 'fulfilled') setBots(results[2].value as Json);
    if (results[3].status === 'fulfilled') setNews(results[3].value as Json);
    if (results.every(x => x.status === 'rejected')) setError('Backend временно недоступен');
  };

  useEffect(() => { void load(); }, []);

  const equity = useMemo(() => asNumber(account?.total_equity, 24356.22), [account]);
  const available = asNumber(account?.total_available_balance, 18640.42);
  const positions = Array.isArray(account?.positions) ? account.positions.length : 4;
  const summary = (bots?.summary ?? {}) as Json;
  const activeBots = asNumber(summary.active, 9);
  const totalBots = asNumber(summary.total_bots, 11);
  const botRows = Array.isArray(bots?.bots) ? (bots?.bots as Json[]) : [];
  const newsRows = Array.isArray(news?.news) ? (news?.news as Json[]) : [];

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
      setChat(v => [...v, { from:'ai', text:'Не удалось связаться с AI API. Интерфейс продолжает работать.' }]);
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => setActive('Обзор')} aria-label="SharipoAI">
          <Image src="/sharipoai-logo.svg" alt="SharipoAI" width={174} height={88} priority />
        </button>
        <nav>
          {NAV.map(([label, Icon]) => (
            <button key={label} className={active === label ? 'active' : ''} onClick={() => setActive(label)}>
              <Icon size={18}/><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="aiMode"><div><Activity size={18}/><span><b>AI-режим</b><small>АКТИВЕН</small></span></div><button><Power size={17}/> Остановить AI</button></div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="welcome"><p>Привет, Самандар! 👋</p><span>SharipoAI работает на полную мощность</span></div>
          <div className="topStatus"><div><small>Статус системы</small><b><i/>Все системы в норме</b></div><div><small>Подключение</small><b className={account ? 'ok' : ''}>{account ? 'Bybit подключён' : 'Проверка Bybit'}</b></div></div>
          <div className="topIcons"><button><Search size={20}/></button><button><Bell size={20}/></button><button onClick={() => void load()}><RefreshCw size={20}/></button></div>
        </header>

        {error && <div className="alert">{error}. Данные-заглушки показаны только для макета; торговое исполнение не включено.</div>}

        {active === 'Обзор' && <Overview equity={equity} available={available} positions={positions} activeBots={activeBots} totalBots={totalBots}/>} 
        {active === 'Рынок' && <MarketPage/>}
        {active === 'AI-решение' && <DecisionPage/>}
        {active === 'Портфель' && <PortfolioPage equity={equity}/>} 
        {active === 'Сделки' && <TradesPage/>}
        {active === 'AI-боты' && <BotsPage rows={botRows} active={activeBots} total={totalBots}/>} 
        {active === 'AI-чат' && <ChatPage chat={chat} message={message} setMessage={setMessage} send={sendMessage}/>} 
        {active === 'Новости' && <NewsPage rows={newsRows}/>} 
        {active === 'Risk Center' && <RiskPage/>}
        {active === 'Bybit' && <BybitPage account={account}/>} 
        {active === 'Настройки' && <SettingsPage/>}
      </section>
    </main>
  );
}

function Metric({label,value,note,kind=''}:{label:string;value:string;note:string;kind?:string}) {
  return <article className="metric"><span>{label}</span><strong className={kind}>{value}</strong><em>{note}</em></article>;
}

function Overview({equity,available,positions,activeBots,totalBots}:{equity:number;available:number;positions:number;activeBots:number;totalBots:number}) {
  return <>
    <section className="metrics">
      <Metric label="Общий баланс" value={`${equity.toLocaleString('ru-RU',{minimumFractionDigits:2})} USDT`} note="≈ USD"/>
      <Metric label="Прибыль за сегодня" value="+314.22 USDT" note="+1.31%" kind="positive"/>
      <Metric label="Открытые позиции" value={String(positions)} note="Активные позиции"/>
      <Metric label="Общий PnL (7 дней)" value="+2 156.87 USDT" note="+9.71%" kind="positive"/>
      <Metric label="Риск системы" value="НИЗКИЙ" note="Уровень риска" kind="positive"/>
    </section>
    <section className="dashboardGrid">
      <article className="panel chartPanel"><PanelHead eyebrow="LIVE CHART" title="График BTC/USDT"/><div className="chartWrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={portfolioSeries}><defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#31d7ff" stopOpacity={.55}/><stop offset="100%" stopColor="#31d7ff" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#18314d" vertical={false}/><XAxis dataKey="t" stroke="#6f839b"/><YAxis stroke="#6f839b"/><Tooltip contentStyle={{background:'#081522',border:'1px solid #244866',borderRadius:12}}/><Area dataKey="v" stroke="#31d7ff" strokeWidth={3} fill="url(#fill)"/></AreaChart></ResponsiveContainer></div></article>
      <article className="panel decisionPanel"><PanelHead eyebrow="AI DECISION" title="Решение AI"/><div className="decision">BUY BTC</div><div className="confidence"><span style={{width:'92%'}}/></div><div className="decisionStats"><div><span>Уверенность</span><b>92%</b></div><div><span>Риск</span><b className="positive">Низкий</b></div></div><ul><li>Бычий тренд на старшем ТФ</li><li>Положительные новости</li><li>Рост объёмов</li><li>Поддержка удержана</li></ul></article>
      <article className="panel marketPanel"><PanelHead eyebrow="LIVE MARKET" title="Рынок сегодня"/>{market.slice(0,5).map(r=><div className="marketRow" key={r[0]}><b>{r[0]}</b><span>{r[1]}</span><em className={r[2].startsWith('-')?'negative':'positive'}>{r[2]}</em></div>)}</article>
      <article className="panel agentsPanel"><PanelHead eyebrow="AI NETWORK" title="Что делает AI сейчас"/>{['Анализирует рынок','Сканирует новости','Проверяет риск','Следит за позициями','Ищет точку входа'].map(x=><div className="agentRow" key={x}><i/><span>{x}</span><small>LIVE</small></div>)}</article>
      <article className="panel portfolioPanel"><PanelHead eyebrow="PORTFOLIO" title="Распределение портфеля"/><div className="donutWrap"><ResponsiveContainer width="55%" height={220}><RePieChart><Pie data={allocation} dataKey="value" innerRadius={58} outerRadius={88} paddingAngle={3}>{allocation.map(x=><Cell key={x.name} fill={x.color}/>)}</Pie></RePieChart></ResponsiveContainer><div>{allocation.map(x=><p key={x.name}><i style={{background:x.color}}/>{x.name}<b>{x.value}%</b></p>)}</div></div></article>
      <article className="panel tradesPanel"><PanelHead eyebrow="EXECUTION" title="Последние сделки"/><table><tbody><tr><td>BTC/USDT</td><td className="positive">BUY</td><td>0.012 BTC</td><td>17:33</td></tr><tr><td>ETH/USDT</td><td className="positive">BUY</td><td>0.45 ETH</td><td>17:28</td></tr><tr><td>SOL/USDT</td><td className="negative">SELL</td><td>12.5 SOL</td><td>17:25</td></tr></tbody></table></article>
      <article className="panel systemPanel"><PanelHead eyebrow="SYSTEM" title={`Статус AI-ботов ${activeBots}/${totalBots}`}/>{['Market AI','News AI','Risk AI','Sentiment AI','Execution AI','Portfolio AI'].map(x=><div className="agentRow" key={x}><i/><span>{x}</span><small>Работает</small></div>)}</article>
      <article className="panel performancePanel"><PanelHead eyebrow="PERFORMANCE" title="Производительность системы"/><div className="miniMetrics"><Metric label="Точность прогнозов" value="89.7%" note="30 дней" kind="positive"/><Metric label="Прибыльность" value="+47.2%" note="30 дней" kind="positive"/><Metric label="Макс. просадка" value="-3.2%" note="контроль" kind="negative"/><Metric label="Коэффициент Шарпа" value="2.31" note="эффективность" kind="positive"/></div></article>
    </section>
  </>;
}

function PanelHead({eyebrow,title}:{eyebrow:string;title:string}) { return <div className="panelHead"><div><span>{eyebrow}</span><h2>{title}</h2></div><ArrowUpRight size={19}/></div>; }
function MarketPage() { return <section className="pageGrid"><article className="panel widePage"><PanelHead eyebrow="MARKETS" title="Рынок в реальном времени"/><div className="marketTable">{market.map(r=><div className="marketRow big" key={r[0]}><b>{r[0]}</b><span>{r[1]}</span><em className={r[2].startsWith('-')?'negative':'positive'}>{r[2]}</em><button>Открыть график</button></div>)}</div></article><article className="panel"><PanelHead eyebrow="HEATMAP" title="Сигналы рынка"/><div className="heatmap">{market.map((r,i)=><div key={r[0]} className={i===2?'down':''}>{r[0]}<b>{r[2]}</b></div>)}</div></article></section>; }
function DecisionPage() { return <section className="pageGrid"><article className="panel heroDecision"><PanelHead eyebrow="AI DECISION" title="BUY BTC"/><div className="decision giant">92%</div><p>Уверенность AI</p><div className="confidence"><span style={{width:'92%'}}/></div><ul><li>Тренд подтверждён</li><li>Новости положительные</li><li>Объём растёт</li><li>Risk Center разрешает наблюдение</li></ul></article><article className="panel"><PanelHead eyebrow="VOTES" title="Голоса AI"/>{['Market AI: BUY','News AI: BUY','Risk AI: WAIT','Sentiment AI: BUY','Portfolio AI: BUY'].map(x=><div className="vote" key={x}>{x}<b>{x.endsWith('WAIT')?'Ожидание':'Подтверждено'}</b></div>)}</article></section>; }
function PortfolioPage({equity}:{equity:number}) { return <section className="pageGrid"><article className="panel widePage"><PanelHead eyebrow="PORTFOLIO" title="Аналитика портфеля"/><div className="chartWrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={portfolioSeries}><CartesianGrid stroke="#18314d" vertical={false}/><XAxis dataKey="t" stroke="#6f839b"/><YAxis stroke="#6f839b"/><Area dataKey="v" stroke="#31d7ff" fill="#31d7ff22"/></AreaChart></ResponsiveContainer></div></article><article className="panel"><h2>{equity.toFixed(2)} USDT</h2><div className="donutWrap single"><ResponsiveContainer width="100%" height={230}><RePieChart><Pie data={allocation} dataKey="value" innerRadius={62} outerRadius={95}>{allocation.map(x=><Cell key={x.name} fill={x.color}/>)}</Pie></RePieChart></ResponsiveContainer></div></article></section>; }
function TradesPage() { return <article className="panel"><PanelHead eyebrow="TRADES" title="История сделок"/><table className="fullTable"><thead><tr><th>Пара</th><th>Сторона</th><th>Объём</th><th>Цена</th><th>PnL</th><th>Статус</th></tr></thead><tbody>{[['BTC/USDT','BUY','0.012','118432','+118.27','Закрыта'],['ETH/USDT','SELL','0.45','2987','+123.46','Закрыта'],['SOL/USDT','BUY','12.5','167.45','-21.34','Открыта']].map(r=><tr key={r[0]}>{r.map((x,i)=><td key={i} className={i===4?(x.startsWith('+')?'positive':'negative'):''}>{x}</td>)}</tr>)}</tbody></table></article>; }
function BotsPage({rows,active,total}:{rows:Json[];active:number;total:number}) { const names=rows.length?rows.map(x=>String(x.name??'AI Agent')):['General Controller','Market AI','News AI','Risk AI','Sentiment AI','Execution AI','Portfolio AI']; return <><section className="metrics"><Metric label="Всего AI" value={String(total)} note="в системе"/><Metric label="Активны" value={String(active)} note="сейчас" kind="positive"/><Metric label="Предупреждения" value={String(Math.max(total-active,0))} note="требуют внимания"/></section><section className="botGrid">{names.map((n,i)=><article className="panel botCard" key={n}><Bot/><h3>{n}</h3><span className="positive">Работает</span><p>Последнее действие: {i%2?'Проверка данных':'Анализ рынка'}</p><button>Открыть AI</button></article>)}</section></>; }
function ChatPage({chat,message,setMessage,send}:{chat:Array<{from:'user'|'ai';text:string}>;message:string;setMessage:(v:string)=>void;send:(e:React.FormEvent)=>void}) { return <article className="panel chatPage"><PanelHead eyebrow="AI COPILOT" title="Чат с SharipoAI"/><div className="chatLog">{chat.map((m,i)=><div key={i} className={`bubble ${m.from}`}><b>{m.from==='ai'?'SharipoAI':'Самандар'}</b><p>{m.text}</p></div>)}</div><form onSubmit={send}><textarea value={message} onChange={e=>setMessage(e.target.value)} placeholder="Напиши команду или вопрос…"/><button>Отправить</button></form></article>; }
function NewsPage({rows}:{rows:Json[]}) { const list=rows.length?rows.slice(0,8).map(x=>({title:String(x.title??x.headline??'Новость рынка'),source:String(x.source??'Источник')})):[{title:'Bitcoin обновил локальный максимум',source:'Market feed'},{title:'ETF-потоки поддерживают рынок',source:'News AI'},{title:'Рост активности по BTC',source:'On-chain'}]; return <section className="newsGrid">{list.map((n,i)=><article className="panel newsCard" key={i}><Newspaper/><div><small>{n.source}</small><h3>{n.title}</h3><p>AI влияние: {i%3===0?'Высокое':'Среднее'}</p></div></article>)}</section>; }
function RiskPage() { return <section className="pageGrid"><article className="panel riskHero"><PanelHead eyebrow="RISK CENTER" title="Текущий уровень: НИЗКИЙ"/><div className="riskGauge">28<small>/100</small></div><p>Kill switch активен для реальных ордеров до отдельного подтверждения.</p></article><article className="panel"><PanelHead eyebrow="LIMITS" title="Ограничения"/>{[['Риск на сделку','2%'],['Дневной риск','6%'],['Макс. просадка','10%'],['Кредитное плечо','3x']].map(x=><div className="limit" key={x[0]}><span>{x[0]}</span><b>{x[1]}</b></div>)}</article></section>; }
function BybitPage({account}:{account:Json|null}) { const connected=Boolean(account); return <section className="pageGrid"><article className="panel bybitHero"><PanelHead eyebrow="BYBIT ACCOUNT" title={connected?'Личный кабинет подключён':'Подключение не подтверждено'}/><div className={`connection ${connected?'ok':''}`}><i/>{connected?'API подключён':'Проверка API'}</div><div className="metrics embedded"><Metric label="Баланс" value={`${asNumber(account?.total_equity,0).toFixed(2)} USDT`} note="Unified Account"/><Metric label="Доступно" value={`${asNumber(account?.total_available_balance,0).toFixed(2)} USDT`} note="Свободно"/><Metric label="Позиции" value={String(Array.isArray(account?.positions)?account.positions.length:0)} note="Открыто"/></div></article><article className="panel"><PanelHead eyebrow="SECURITY" title="Безопасность"/><p>Ключи хранятся только в секретах Render. Вывод средств не требуется. Реальное исполнение отделено kill switch.</p><div className="securityList"><b>✓ Read account</b><b>✓ Read positions</b><b>✓ Read orders</b><b>✕ Withdraw disabled</b></div></article></section>; }
function SettingsPage() { return <section className="settingsGrid">{['Общие','Уведомления','Торговля','Безопасность','Интеграции','Внешний вид'].map(x=><article className="panel settingCard" key={x}><Settings/><div><h3>{x}</h3><p>Параметры SharipoAI</p></div><button>Открыть</button></article>)}</section>; }
