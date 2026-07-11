(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const nav = $('nav'), content = $('content'), notice = $('notice'), refresh = $('refresh');
  const state = { health:null, run:null, account:null, bots:null, news:null, learning:null, evidence:null, virtual:null, report:null };
  const market = { symbol:'BTCUSDT', interval:'15', candles:[], quote:null, orderbook:null, timer:null };
  let lang = localStorage.getItem('sharipovai-lang') || 'ru';
  let page = 'overview';
  if (!nav || !content) return;

  const L = {
    ru:{nav:['Обзор','Рынок','Решение ИИ','Портфель','Сделки','ИИ-модули','ИИ-чат','Новости','Центр рисков','Bybit','Центр обучения','Главное управление','Хранилище доказательств','Виртуальный счёт','Отчёты','Настройки'],hello:'Привет, Самандар 👋',sub:'SharipovAI — единый центр анализа, управления и контроля',refresh:'Обновить',starting:'Система запускается',safe:'Безопасное исполнение',active:'Режим ИИ активен'},
    en:{nav:['Overview','Market','AI decision','Portfolio','Trades','AI modules','AI chat','News','Risk center','Bybit','Learning center','Main control','Evidence vault','Virtual account','Reports','Settings'],hello:'Hello, Samandar 👋',sub:'SharipovAI — unified analysis, control and monitoring center',refresh:'Refresh',starting:'System is starting',safe:'Safe execution',active:'AI mode active'},
    uz:{nav:['Umumiy ko‘rinish','Bozor','AI qarori','Portfel','Bitimlar','AI modullari','AI chat','Yangiliklar','Xavf markazi','Bybit','O‘qitish markazi','Bosh boshqaruv','Dalillar ombori','Virtual hisob','Hisobotlar','Sozlamalar'],hello:'Salom, Samandar 👋',sub:'SharipovAI — tahlil, boshqaruv va nazorat markazi',refresh:'Yangilash',starting:'Tizim ishga tushmoqda',safe:'Xavfsiz ijro',active:'AI rejimi faol'}
  };
  const pages = ['overview','market','decision','portfolio','trades','bots','chat','news','risk','bybit','learning','control','evidence','virtual','reports','settings'];
  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = v => Number(v||0).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:8});
  const title = (h,p) => `<div class="title"><h1>${esc(h)}</h1><p>${esc(p)}</p></div>`;
  const card = (l,v,n,c='') => `<article class="card"><span>${esc(l)}</span><strong class="${c}">${esc(v)}</strong><small>${esc(n)}</small></article>`;
  const panel = (h,b,c='') => `<article class="panel ${c}"><small>SHARIPOVAI</small><h2>${esc(h)}</h2>${b}</article>`;
  const empty = t => `<div class="empty">${esc(t)}</div>`;
  const status = (l,v,ok=true) => `<div><span>${esc(l)}</span><b class="${ok?'positive':'negative'}">${esc(v)}</b></div>`;
  const tr = (ru,en,uz) => lang==='en'?en:lang==='uz'?uz:ru;

  function applyLanguage(){
    const d=L[lang]; document.documentElement.lang=lang;
    [...nav.querySelectorAll('button[data-page]')].forEach((b,i)=>b.textContent=d.nav[i]);
    $('helloLabel').textContent=d.hello; $('subtitleLabel').textContent=d.sub; refresh.textContent=d.refresh;
    $('aiModeLabel').textContent=d.active; if(!$('modeText').dataset.dynamic)$('modeText').textContent=d.safe;
    document.querySelectorAll('[data-lang]').forEach(b=>b.classList.toggle('active',b.dataset.lang===lang));
    render();
  }

  function account(){ const x=state.account?.snapshot||state.account?.account||state.account?.result||state.account||{}; return {equity:x.total_equity??x.totalEquity??x.equity,available:x.total_available_balance??x.totalAvailableBalance??x.available_balance,positions:Array.isArray(x.positions)?x.positions:[],connected:Boolean(state.account&&!state.account.error)}; }
  function overview(){ const a=account(); const r=state.run||{}; return title(tr('Центр управления','Control center','Boshqaruv markazi'),tr('Фактическое состояние системы без выдуманных показателей','Verified system state without invented figures','To‘qima raqamlarsiz tizim holati'))+`<section class="metrics">${card(tr('Общий баланс','Total balance','Umumiy balans'),a.equity!=null?`${num(a.equity)} USDT`:'—',a.connected?'Bybit':'')}${card(tr('Доступно','Available','Mavjud'),a.available!=null?`${num(a.available)} USDT`:'—','')}${card(tr('Открытые позиции','Open positions','Ochiq pozitsiyalar'),a.positions.length,'')}${card(tr('Решение ИИ','AI decision','AI qarori'),r.decision||'—','')}${card(tr('Риск','Risk','Xavf'),r.risk_level||'—','')}</section>${panel(tr('Рынок','Market','Bozor'),market.quote?`${card(market.symbol,`${num(market.quote.price)} USDT`,`${market.quote.source} · ${new Date(market.quote.received_at).toLocaleTimeString()}`)}`:empty(tr('Котировка загружается','Quote is loading','Kotirovka yuklanmoqda')),'wide')}`; }

  function marketPage(){
    const q=market.quote||{}; const c=market.candles||[]; const latest=c[c.length-1]||{};
    return title(tr('Рынок','Market','Bozor'),tr('Реальные свечи и котировки с Bybit','Real candles and quotes from Bybit','Bybit dan haqiqiy shamlar va kotirovkalar'))+
    `<div class="market-toolbar"><select id="symbolSelect">${['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT'].map(s=>`<option ${s===market.symbol?'selected':''}>${s}</option>`).join('')}</select><div class="intervals">${['1','5','15','60','240','D'].map(i=>`<button data-interval="${i}" class="${i===market.interval?'active':''}">${i==='D'?'1Д':i+'м'}</button>`).join('')}</div><span class="source-badge">Bybit · ${q.received_at?new Date(q.received_at).toLocaleTimeString():'—'}</span></div>`+
    `<section class="metrics">${card(tr('Последняя цена','Last price','Oxirgi narx'),q.price!=null?`${num(q.price)} USDT`:'—',tr('Проверенная котировка','Verified quote','Tasdiqlangan kotirovka'))}${card(tr('Изменение за 24 часа','24h change','24 soatlik o‘zgarish'),q.change_24h_percent!=null?`${num(q.change_24h_percent)}%`:'—','',Number(q.change_24h_percent)>=0?'positive':'negative')}${card(tr('Объём за 24 часа','24h volume','24 soatlik hajm'),q.volume_24h!=null?num(q.volume_24h):'—','USDT')}${card(tr('Последняя свеча','Latest candle','Oxirgi sham'),latest.close!=null?num(latest.close):'—',market.interval)}</section>`+
    `${panel(tr('Свечной график','Candlestick chart','Shamlar grafigi'),`<div class="chart-wrap"><canvas id="candleChart" height="420"></canvas><div id="chartMessage" class="chart-message hidden"></div></div>`,'wide')}`+
    `<section class="grid">${panel(tr('Объём','Volume','Hajm'),`<canvas id="volumeChart" height="170"></canvas>`,'wide')}${panel(tr('Книга заявок','Order book','Buyurtmalar kitobi'),orderBookHtml())}</section>`;
  }

  function orderBookHtml(){ const o=market.orderbook; if(!o)return empty(tr('Загрузка книги заявок','Loading order book','Buyurtmalar kitobi yuklanmoqda')); const rows=[]; const asks=(o.asks||[]).slice(0,8).reverse(); const bids=(o.bids||[]).slice(0,8); asks.forEach(x=>rows.push(`<div class="book-row ask"><span>${num(x[0])}</span><span>${num(x[1])}</span></div>`)); bids.forEach(x=>rows.push(`<div class="book-row bid"><span>${num(x[0])}</span><span>${num(x[1])}</span></div>`)); return `<div class="book-head"><span>${tr('Цена','Price','Narx')}</span><span>${tr('Количество','Amount','Miqdor')}</span></div>${rows.join('')}`; }

  function simplePage(key){
    const a=account(), r=state.run||{}, bots=state.bots?.bots||[];
    if(key==='decision')return title(tr('Решение ИИ','AI decision','AI qarori'),tr('Консенсус и объяснение','Consensus and explanation','Konsensus va izoh'))+panel(tr('Текущее решение','Current decision','Joriy qaror'),`<div class="status-list">${status(tr('Решение','Decision','Qaror'),r.decision||'—',true)}${status(tr('Уверенность','Confidence','Ishonch'),r.confidence!=null?r.confidence+'%':'—',true)}${status(tr('Риск','Risk','Xavf'),r.risk_level||'—',true)}</div><p>${esc(r.reason||tr('Объяснение пока не получено','No explanation yet','Izoh hali olinmadi'))}</p>`,'wide');
    if(key==='portfolio')return title(tr('Портфель','Portfolio','Portfel'),'')+`<section class="metrics">${card(tr('Капитал','Equity','Kapital'),a.equity!=null?num(a.equity)+' USDT':'—','')}${card(tr('Доступно','Available','Mavjud'),a.available!=null?num(a.available)+' USDT':'—','')}${card(tr('Позиции','Positions','Pozitsiyalar'),a.positions.length,'')}</section>`;
    if(key==='trades')return title(tr('Сделки','Trades','Bitimlar'),'')+panel(tr('История','History','Tarix'),empty(tr('Отображаются только подтверждённые сделки','Only verified trades are shown','Faqat tasdiqlangan bitimlar ko‘rsatiladi')),'wide');
    if(key==='bots')return title(tr('ИИ-модули','AI modules','AI modullari'),'')+(bots.length?`<section class="bot-grid">${bots.map(b=>panel(b.name||tr('ИИ-модуль','AI module','AI moduli'),`<div class="status-list">${status(tr('Статус','Status','Holat'),b.heartbeat_age_seconds!=null&&b.heartbeat_age_seconds<60?tr('Подтверждён','Verified','Tasdiqlangan'):tr('Не подтверждён','Unverified','Tasdiqlanmagan'),b.heartbeat_age_seconds!=null&&b.heartbeat_age_seconds<60)}${status(tr('Качество','Quality','Sifat'),b.metrics_verified&&b.quality_score!=null?b.quality_score+'%':tr('Нет измерений','No measurements','O‘lchov yo‘q'),Boolean(b.metrics_verified))}${status(tr('Последнее действие','Last action','Oxirgi amal'),b.evidence_id&&b.last_action?b.last_action:tr('Нет подтверждённого события','No verified event','Tasdiqlangan hodisa yo‘q'),Boolean(b.evidence_id))}</div>`)).join('')}</section>`:panel(tr('Нет данных','No data','Ma’lumot yo‘q'),empty(tr('Список модулей не получен','Module list was not received','Modullar ro‘yxati olinmadi')),'wide'));
    if(key==='risk')return title(tr('Центр рисков','Risk center','Xavf markazi'),'')+panel(tr('Проверки','Checks','Tekshiruvlar'),`<div class="status-list">${status(tr('Вывод средств','Withdrawals','Pul yechish'),tr('Запрещён','Blocked','Taqiqlangan'),true)}${status(tr('Лимиты позиции','Position limits','Pozitsiya limitlari'),tr('Активны','Active','Faol'),true)}</div>`,'wide');
    if(key==='bybit')return title('Bybit','')+`<section class="metrics">${card(tr('Подключение','Connection','Ulanish'),a.connected?tr('Подключён','Connected','Ulangan'):tr('Не подключён','Not connected','Ulanmagan'),'',a.connected?'positive':'negative')}${card(tr('Капитал','Equity','Kapital'),a.equity!=null?num(a.equity)+' USDT':'—','')}</section>`;
    if(key==='settings')return title(tr('Настройки','Settings','Sozlamalar'),tr('Язык, безопасность и интерфейс','Language, security and interface','Til, xavfsizlik va interfeys'))+panel(tr('Язык интерфейса','Interface language','Interfeys tili'),`<p>Русский · English · O‘zbek</p>`,'wide');
    if(key==='chat')return title(tr('ИИ-чат','AI chat','AI chat'),'')+panel('SharipovAI',`<div class="chat"><div id="messages" class="messages"><div class="bubble">${tr('Я онлайн. Спроси о рынке или портфеле.','I am online. Ask about the market or portfolio.','Men onlaynman. Bozor yoki portfel haqida so‘rang.')}</div></div><form id="chatForm"><input id="msg"><button class="action">${tr('Отправить','Send','Yuborish')}</button></form></div>`,'wide');
    const names={news:tr('Новости','News','Yangiliklar'),learning:tr('Центр обучения','Learning center','O‘qitish markazi'),control:tr('Главное управление','Main control','Bosh boshqaruv'),evidence:tr('Хранилище доказательств','Evidence vault','Dalillar ombori'),virtual:tr('Виртуальный счёт','Virtual account','Virtual hisob'),reports:tr('Отчёты','Reports','Hisobotlar')};
    return title(names[key]||'',tr('Раздел использует только подтверждённые данные','This section uses verified data only','Bu bo‘lim faqat tasdiqlangan ma’lumotlardan foydalanadi'))+panel(names[key]||'',empty(tr('Данные пока не получены','No data received yet','Ma’lumot hali olinmadi')),'wide');
  }

  function render(){ content.innerHTML=page==='market'?marketPage():page==='overview'?overview():simplePage(page); if(page==='market'){bindMarketControls(); requestAnimationFrame(drawCharts);} if(page==='chat')bindChat(); }
  function bindMarketControls(){ const s=$('symbolSelect'); if(s)s.onchange=()=>{market.symbol=s.value;loadMarket(true)}; document.querySelectorAll('[data-interval]').forEach(b=>b.onclick=()=>{market.interval=b.dataset.interval;loadMarket(true)}); }
  function bindChat(){ const f=$('chatForm'); if(!f)return; f.onsubmit=async e=>{e.preventDefault();const i=$('msg'),m=$('messages'),t=i.value.trim();if(!t)return;m.insertAdjacentHTML('beforeend',`<div class="bubble user">${esc(t)}</div>`);i.value='';try{const j=await get('/api/chat/message',{method:'POST'});m.insertAdjacentHTML('beforeend',`<div class="bubble">${esc(j.reply||'—')}</div>`)}catch{m.insertAdjacentHTML('beforeend',`<div class="bubble">${tr('ИИ временно недоступен','AI is temporarily unavailable','AI vaqtincha mavjud emas')}</div>`)}}; }

  function drawCharts(){ drawCandleCanvas($('candleChart'),market.candles); drawVolumeCanvas($('volumeChart'),market.candles); }
  function prepCanvas(canvas){ if(!canvas)return null; const dpr=window.devicePixelRatio||1,w=canvas.clientWidth||900,h=Number(canvas.getAttribute('height'))||400; canvas.width=w*dpr;canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);return {ctx,w,h}; }
  function drawCandleCanvas(canvas,data){ const p=prepCanvas(canvas); if(!p)return; const {ctx,w,h}=p;ctx.clearRect(0,0,w,h);if(!data.length){ctx.fillStyle='#7f93a8';ctx.fillText(tr('Нет свечей','No candles','Shamlar yo‘q'),20,30);return;} const pad={l:16,r:72,t:20,b:28}, plotW=w-pad.l-pad.r,plotH=h-pad.t-pad.b;const lo=Math.min(...data.map(x=>x.low)),hi=Math.max(...data.map(x=>x.high)),range=hi-lo||1;const y=v=>pad.t+(hi-v)/range*plotH;ctx.strokeStyle='#173957';ctx.lineWidth=1;for(let i=0;i<5;i++){const yy=pad.t+i*plotH/4;ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.fillStyle='#7f93a8';ctx.font='11px sans-serif';ctx.fillText(num(hi-i*range/4),w-pad.r+6,yy+4);} const step=plotW/data.length,body=Math.max(2,step*.62);data.forEach((c,i)=>{const x=pad.l+i*step+step/2,up=c.close>=c.open;color=up?'#3be08f':'#ff6f7d';ctx.strokeStyle=color;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(x,y(c.high));ctx.lineTo(x,y(c.low));ctx.stroke();const top=Math.min(y(c.open),y(c.close)),bh=Math.max(1,Math.abs(y(c.open)-y(c.close)));ctx.fillRect(x-body/2,top,body,bh);}); }
  function drawVolumeCanvas(canvas,data){ const p=prepCanvas(canvas); if(!p)return;const {ctx,w,h}=p;ctx.clearRect(0,0,w,h);if(!data.length)return;const max=Math.max(...data.map(x=>x.volume))||1,step=w/data.length,bw=Math.max(2,step*.65);data.forEach((c,i)=>{ctx.fillStyle=c.close>=c.open?'#3be08f88':'#ff6f7d88';const bh=(c.volume/max)*(h-20);ctx.fillRect(i*step+(step-bw)/2,h-bh,bw,bh);}); }

  async function get(url,opts){ const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...(opts||{})}); if(!r.ok)throw new Error(`${url}: ${r.status}`);return r.json(); }
  async function loadMarket(force=false){
    if(force){market.candles=[];render();}
    const [q,c,o]=await Promise.allSettled([get(`/api/market/quote/${market.symbol}`),get(`/api/market/candles/${market.symbol}?interval=${market.interval}&limit=180&category=spot`),get(`/api/market/orderbook/${market.symbol}?limit=25&category=spot`)]);
    if(q.status==='fulfilled')market.quote=q.value;if(c.status==='fulfilled')market.candles=c.value.candles||[];if(o.status==='fulfilled')market.orderbook=o.value;
    if(page==='market'||page==='overview')render();
  }
  async function loadBase(){
    if(notice)notice.classList.add('hidden');
    const endpoints={health:'/api/health',run:'/api/run',account:'/api/exchange/account/snapshot',bots:'/api/ai-bots',news:'/api/social-news',learning:'/api/learning-os/status',evidence:'/api/evidence-vault/recent',virtual:'/api/virtual-account/state',report:'/api/ai-control-center/daily-report'};
    const entries=Object.entries(endpoints),rs=await Promise.allSettled(entries.map(([,u])=>get(u)));rs.forEach((r,i)=>{if(r.status==='fulfilled')state[entries[i][0]]=r.value});const ok=rs.filter(x=>x.status==='fulfilled').length;
    $('systemLabel').textContent=ok?tr(`Система работает · ${ok}/${entries.length} API`,`System online · ${ok}/${entries.length} APIs`,`Tizim ishlamoqda · ${ok}/${entries.length} API`):tr('API недоступен','API unavailable','API mavjud emas');
    if(ok<entries.length&&notice){notice.textContent=tr(`Часть источников недоступна (${ok}/${entries.length}).`,`Some sources are unavailable (${ok}/${entries.length}).`,`Ayrim manbalar mavjud emas (${ok}/${entries.length}).`);notice.classList.remove('hidden');}
    render();
  }

  nav.querySelectorAll('button[data-page]').forEach(b=>b.onclick=()=>{nav.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');page=b.dataset.page;render();});
  document.querySelectorAll('[data-lang]').forEach(b=>b.onclick=()=>{lang=b.dataset.lang;localStorage.setItem('sharipovai-lang',lang);applyLanguage();});
  refresh.onclick=()=>{loadBase();loadMarket(true)};
  window.addEventListener('resize',()=>{if(page==='market')drawCharts()});
  applyLanguage();loadBase();loadMarket();market.timer=setInterval(()=>loadMarket(false),5000);
})();