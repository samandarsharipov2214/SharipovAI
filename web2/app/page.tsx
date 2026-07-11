'use client';

import { useEffect, useMemo, useState } from 'react';
import { Activity, Bot, BrainCircuit, CandlestickChart, CircleDollarSign, LayoutDashboard, MessageSquareText, Newspaper, PieChart, Settings, ShieldCheck, WalletCards } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type ApiState = Record<string, unknown>;

const nav = [
  ['Обзор', LayoutDashboard], ['Рынок', CandlestickChart], ['AI-решение', BrainCircuit], ['Портфель', PieChart],
  ['Сделки', CircleDollarSign], ['AI-боты', Bot], ['AI-чат', MessageSquareText], ['Новости', Newspaper],
  ['Risk Center', ShieldCheck], ['Bybit', WalletCards], ['Настройки', Settings],
] as const;

const chart = [
  { t: '09:00', v: 22140 }, { t: '10:00', v: 22260 }, { t: '11:00', v: 22190 },
  { t: '12:00', v: 22420 }, { t: '13:00', v: 22370 }, { t: '14:00', v: 22610 },
  { t: '15:00', v: 22545 },
];

function apiUrl(path: string) {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, '') ?? '';
  return `${base}${path}`;
}

export default function Home() {
  const [active, setActive] = useState('Обзор');
  const [health, setHealth] = useState<ApiState | null>(null);
  const [account, setAccount] = useState<ApiState | null>(null);
  const [bots, setBots] = useState<ApiState | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.allSettled([
      fetch(apiUrl('/api/health')).then(r => r.json()),
      fetch(apiUrl('/api/exchange/account/snapshot')).then(r => r.json()),
      fetch(apiUrl('/api/ai-bots')).then(r => r.json()),
    ]).then(([h, a, b]) => {
      if (h.status === 'fulfilled') setHealth(h.value);
      if (a.status === 'fulfilled') setAccount(a.value);
      if (b.status === 'fulfilled') setBots(b.value);
      if ([h, a, b].every(x => x.status === 'rejected')) setError('Backend временно недоступен');
    });
  }, []);

  const equity = useMemo(() => Number(account?.total_equity ?? 22545.16), [account]);
  const available = Number(account?.total_available_balance ?? 18640.42);
  const positions = Array.isArray(account?.positions) ? account.positions.length : 4;
  const activeBots = Number((bots?.summary as ApiState | undefined)?.active ?? 12);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">SA</div>
          <div><strong>SharipoAI</strong><span>AI Trading OS</span></div>
        </div>
        <nav>
          {nav.map(([label, Icon]) => (
            <button key={label} className={active === label ? 'active' : ''} onClick={() => setActive(label)}>
              <Icon size={18} /> <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sideStatus"><i /> Система работает</div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">MISSION CONTROL</p>
            <h1>{active}</h1>
            <p className="subtitle">Автономная система анализа, риска и исполнения</p>
          </div>
          <div className="topActions">
            <span className="live"><i /> LIVE</span>
            <span>{health ? 'API подключён' : 'Проверка API'}</span>
          </div>
        </header>

        {error && <div className="alert">{error}. Интерфейс продолжает работать в безопасном режиме.</div>}

        <section className="metrics">
          <article><span>Общий капитал</span><strong>{equity.toLocaleString('ru-RU', { minimumFractionDigits: 2 })} USDT</strong><em>+2.38% сегодня</em></article>
          <article><span>Доступно</span><strong>{available.toLocaleString('ru-RU', { minimumFractionDigits: 2 })} USDT</strong><em>Свободные средства</em></article>
          <article><span>Открытые позиции</span><strong>{positions}</strong><em>Под контролем AI</em></article>
          <article><span>AI-боты</span><strong>{activeBots}</strong><em>активны сейчас</em></article>
        </section>

        <section className="dashboardGrid">
          <article className="panel chartPanel">
            <div className="panelHead"><div><span>Капитал</span><h2>Динамика портфеля</h2></div><b className="positive">+523.44 USDT</b></div>
            <div className="chartWrap">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chart}>
                  <defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#31d7ff" stopOpacity={0.55}/><stop offset="100%" stopColor="#31d7ff" stopOpacity={0}/></linearGradient></defs>
                  <CartesianGrid stroke="#18314d" vertical={false}/><XAxis dataKey="t" stroke="#6f839b"/><YAxis stroke="#6f839b" domain={['dataMin - 100', 'dataMax + 100']}/><Tooltip contentStyle={{ background: '#081522', border: '1px solid #244866', borderRadius: 12 }}/><Area type="monotone" dataKey="v" stroke="#31d7ff" strokeWidth={3} fill="url(#fill)"/>
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </article>

          <article className="panel decisionPanel">
            <div className="panelHead"><div><span>AI DECISION</span><h2>Текущее решение</h2></div><Activity size={22}/></div>
            <div className="decision">BUY BTC</div>
            <div className="confidence"><span style={{ width: '92%' }} /></div>
            <div className="decisionStats"><div><span>Уверенность</span><b>92%</b></div><div><span>Риск</span><b className="positive">Низкий</b></div></div>
            <p>Рыночный импульс подтверждён объёмом. Исполнение разрешается только после проверки Risk Center.</p>
          </article>

          <article className="panel marketPanel">
            <div className="panelHead"><div><span>LIVE MARKET</span><h2>Рынок</h2></div><CandlestickChart size={22}/></div>
            {[['BTC/USDT','64 235.21','+2.35%'],['ETH/USDT','3 124.80','+1.78%'],['SOL/USDT','154.36','+3.12%'],['BNB/USDT','612.44','+0.84%']].map(row => <div className="marketRow" key={row[0]}><b>{row[0]}</b><span>{row[1]}</span><em>{row[2]}</em></div>)}
          </article>

          <article className="panel agentsPanel">
            <div className="panelHead"><div><span>AI NETWORK</span><h2>Что делает AI сейчас</h2></div><Bot size={22}/></div>
            {['Market AI анализирует поток','Risk AI проверяет лимиты','News AI оценивает события','Trade Gate ожидает подтверждение'].map((x,i)=><div className="agentRow" key={x}><i className={i===3?'wait':''}/><span>{x}</span><small>{i===3?'WAIT':'LIVE'}</small></div>)}
          </article>

          <article className="panel tradesPanel">
            <div className="panelHead"><div><span>EXECUTION</span><h2>Последние сделки</h2></div><CircleDollarSign size={22}/></div>
            <table><tbody><tr><td>BTC/USDT</td><td>BUY</td><td className="positive">+186.42</td></tr><tr><td>ETH/USDT</td><td>SELL</td><td className="positive">+74.10</td></tr><tr><td>SOL/USDT</td><td>BUY</td><td>-12.40</td></tr></tbody></table>
          </article>
        </section>
      </section>
    </main>
  );
}
