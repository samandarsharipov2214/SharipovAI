(() => {
  "use strict";

  const select = (selector) => document.querySelector(selector);
  const accessView = select("#accessView");
  const workspaceView = select("#workspaceView");
  const message = select("#message");
  const forms = {
    login: select("#loginForm"),
    register: select("#registerForm"),
  };
  const tabs = [...document.querySelectorAll("[data-mode]")];
  const REQUEST_TIMEOUT_MS = 15000;

  function setMessage(text = "", type = "error", target = message) {
    target.textContent = text;
    target.classList.toggle("success", type === "success");
  }

  function setMode(mode, focus = false) {
    const selected = mode === "register" ? "register" : "login";
    tabs.forEach((tab) => {
      const active = tab.dataset.mode === selected;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    Object.entries(forms).forEach(([name, form]) => { form.hidden = name !== selected; });
    setMessage();
    if (focus) forms[selected].querySelector("input")?.focus();
    if (window.location.pathname === "/") {
      const params = new URLSearchParams(window.location.search);
      params.set("mode", selected);
      history.replaceState(null, "", `/?${params.toString()}`);
    }
  }

  function setBusy(form, busy) {
    form.setAttribute("aria-busy", String(busy));
    [...form.elements].forEach((control) => { control.disabled = busy; });
    const label = form.id === "loginForm" ? "Входим…" : "Отправляем…";
    const button = form.querySelector(".primary-action");
    const buttonText = form.querySelector(".primary-action span");
    button.classList.toggle("loading", busy);
    if (busy) {
      buttonText.dataset.original = buttonText.textContent;
      buttonText.textContent = label;
    } else if (buttonText.dataset.original) {
      buttonText.textContent = buttonText.dataset.original;
      delete buttonText.dataset.original;
    }
  }

  async function requestJson(url, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error("request_failed");
        error.status = response.status;
        error.payload = payload;
        throw error;
      }
      return payload;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  const isNetworkError = (error) => !Number.isInteger(error?.status);

  function validate(form) {
    if (!form.checkValidity()) {
      form.reportValidity();
      return false;
    }
    return true;
  }

  tabs.forEach((tab) => tab.addEventListener("click", () => setMode(tab.dataset.mode, true)));
  tabs.forEach((tab) => tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    setMode(tab.dataset.mode === "login" ? "register" : "login", true);
  }));

  document.querySelectorAll("[data-toggle-password]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.togglePassword);
      const visible = input.type === "text";
      input.type = visible ? "password" : "text";
      button.textContent = visible ? "Показать" : "Скрыть";
      button.setAttribute("aria-label", visible ? "Показать пароль" : "Скрыть пароль");
      button.setAttribute("aria-pressed", String(!visible));
      input.focus();
    });
  });

  forms.login.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (forms.login.getAttribute("aria-busy") === "true") return;
    if (!validate(forms.login)) return;
    const values = Object.fromEntries(new FormData(forms.login));
    setMessage();
    setBusy(forms.login, true);
    try {
      await requestJson("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: values.email, password: values.password }),
      });
      window.location.assign("/app");
    } catch (error) {
      const status = error.payload?.detail?.status;
      if (isNetworkError(error)) {
        setMessage("Нет соединения с сервером. Проверьте сеть и повторите попытку.");
      } else if (status === "pending_approval") {
        setMessage("Заявка ещё ожидает одобрения администратора.");
      } else if (status === "access_rejected") {
        setMessage("Заявка на доступ не одобрена.");
      } else if (error.status >= 500) {
        setMessage("Сервис временно недоступен. Повторите попытку позже.");
      } else {
        setMessage("Не удалось войти. Проверьте e-mail и пароль.");
      }
      setBusy(forms.login, false);
    }
  });

  forms.register.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (forms.register.getAttribute("aria-busy") === "true") return;
    if (!validate(forms.register)) return;
    const values = Object.fromEntries(new FormData(forms.register));
    if (values.password !== values.password_confirmation) {
      setMessage("Пароли не совпадают.");
      select("#registerPasswordConfirmation").focus();
      return;
    }
    setMessage();
    setBusy(forms.register, true);
    try {
      await requestJson("/api/auth/register", { method: "POST", body: JSON.stringify(values) });
      forms.register.reset();
      setMessage("Заявка отправлена. После одобрения вы сможете войти.", "success");
    } catch (error) {
      const status = error.payload?.detail?.status;
      if (isNetworkError(error)) {
        setMessage("Нет соединения с сервером. Проверьте сеть и повторите попытку.");
      } else if (status === "already_exists") {
        setMessage("Аккаунт с таким e-mail уже существует или заявка уже отправлена.");
      } else if (error.status >= 500) {
        setMessage("Сервис временно недоступен. Повторите попытку позже.");
      } else {
        setMessage("Проверьте заполненные поля и повторите попытку.");
      }
    } finally {
      setBusy(forms.register, false);
    }
  });

  function formatMoney(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "нет данных";
    return value.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatCount(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "нет данных";
    return String(value);
  }

  function formatPositions(positions) {
    if (!positions || typeof positions !== "object" || Array.isArray(positions)) return "нет данных";
    const symbols = Object.keys(positions);
    if (!symbols.length) return "нет открытых позиций";
    return symbols.join(", ");
  }

  function formatMode(payload) {
    if (!payload || payload.data_available !== true) return "UNAVAILABLE";
    const mode = String(payload.mode || "").toUpperCase();
    if (mode.includes("PAPER")) return "PAPER";
    return mode || "PAPER";
  }

  function formatTime(value) {
    if (value == null || value === "") return "нет данных";
    const numeric = Number(value);
    const date = new Date(Number.isFinite(numeric) && numeric > 0 && numeric < 1e12 ? numeric * 1000 : value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("ru-RU");
  }

  function navButtons() {
    return [...document.querySelectorAll("[data-os-page]")];
  }

  function ensureStubPanels() {
    const mount = select("#osStubMount");
    navButtons().filter((button) => button.dataset.osStub === "1").forEach((button) => {
      const page = button.dataset.osPage;
      if (document.querySelector(`[data-os-panel="${page}"]`)) return;
      const section = document.createElement("section");
      section.className = "os-page";
      section.dataset.osPanel = page;
      section.hidden = true;
      const heading = document.createElement("h2");
      heading.textContent = button.querySelector(".os-nav-label")?.textContent || page;
      const copy = document.createElement("p");
      copy.textContent = `Раздел «${heading.textContent}» скоро появится в Site V1. Сейчас здесь нет данных.`;
      section.append(heading, copy);
      mount.append(section);
    });
  }

  function setOsPage(page) {
    const requested = String(page || "overview");
    const known = navButtons().some((button) => button.dataset.osPage === requested);
    const selected = known ? requested : "overview";
    navButtons().forEach((button) => {
      const active = button.dataset.osPage === selected;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    document.querySelectorAll("[data-os-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.osPanel !== selected;
    });
    if (window.location.pathname === "/app") {
      const next = selected === "overview" ? "/app" : `/app#${selected}`;
      if (`${window.location.pathname}${window.location.hash}` !== next) {
        history.replaceState(null, "", next);
      }
    }
  }

  function currentOsPage() {
    const hash = window.location.hash.replace("#", "").trim();
    return hash || "overview";
  }

  function setTruth(container, kind, title, text) {
    container.replaceChildren();
    const box = document.createElement("div");
    box.className = kind === "unavailable" ? "truthful-state cabinet-unavailable" : "truthful-state";
    const mark = document.createElement("span");
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = kind === "unavailable" ? "!" : "·";
    const body = document.createElement("div");
    const heading = document.createElement("b");
    heading.textContent = title;
    const copy = document.createElement("p");
    copy.textContent = text;
    body.append(heading, copy);
    box.append(mark, body);
    container.append(box);
  }

  function kvGrid(container, rows) {
    container.replaceChildren();
    const grid = document.createElement("div");
    grid.className = "os-kv";
    rows.forEach(([label, value]) => {
      const article = document.createElement("article");
      const eyebrow = document.createElement("p");
      eyebrow.className = "eyebrow";
      eyebrow.textContent = label;
      const bold = document.createElement("b");
      bold.textContent = value;
      article.append(eyebrow, bold);
      grid.append(article);
    });
    container.append(grid);
  }

  function fillTable(container, headers, rows, emptyTitle, emptyText) {
    container.replaceChildren();
    if (!rows.length) {
      setTruth(container, "empty", emptyTitle, emptyText);
      return;
    }
    const table = document.createElement("table");
    table.className = "os-table";
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    headers.forEach((label) => {
      const th = document.createElement("th");
      th.textContent = label;
      headRow.append(th);
    });
    thead.append(headRow);
    const tbody = document.createElement("tbody");
    rows.forEach((cells) => {
      const tr = document.createElement("tr");
      cells.forEach((cell) => {
        const td = document.createElement("td");
        td.textContent = cell;
        tr.append(td);
      });
      tbody.append(tr);
    });
    table.append(thead, tbody);
    container.append(table);
  }

  function positionRows(positions) {
    if (!positions || typeof positions !== "object" || Array.isArray(positions)) return [];
    return Object.entries(positions).map(([symbol, item]) => {
      const row = item && typeof item === "object" ? item : {};
      return [
        String(symbol || "нет данных"),
        formatCount(typeof row.quantity === "number" ? row.quantity : Number(row.quantity)),
        formatMoney(typeof row.entry_price === "number" ? row.entry_price : Number(row.entry_price)),
        formatTime(row.opened_at),
        String(row.reason || "нет данных"),
      ];
    });
  }

  function tradeRows(trades) {
    if (!Array.isArray(trades)) return [];
    return trades.slice(-20).map((item) => {
      const row = item && typeof item === "object" ? item : {};
      return [
        formatTime(row.created_at_ms || row.time),
        String(row.symbol || "нет данных"),
        String(row.side || "нет данных"),
        formatCount(typeof row.quantity === "number" ? row.quantity : Number(row.quantity)),
        formatMoney(typeof row.price === "number" ? row.price : Number(row.price)),
        formatMoney(typeof row.fee === "number" ? row.fee : Number(row.fee)),
        row.net_pnl == null ? "нет данных" : formatMoney(typeof row.net_pnl === "number" ? row.net_pnl : Number(row.net_pnl)),
        String(row.reason || "нет данных"),
      ];
    });
  }

  function collectSymbols(payload) {
    const symbols = [];
    const seen = new Set();
    const add = (value) => {
      const symbol = String(value || "").trim().toUpperCase();
      if (!symbol || seen.has(symbol)) return;
      seen.add(symbol);
      symbols.push(symbol);
    };
    if (payload?.positions && typeof payload.positions === "object" && !Array.isArray(payload.positions)) {
      Object.keys(payload.positions).forEach(add);
    }
    if (Array.isArray(payload?.trades)) {
      payload.trades.forEach((item) => add(item && item.symbol));
    }
    return symbols;
  }

  function showUnavailable(error) {
    select("#cabinetMetrics").hidden = true;
    select("#cabinetActivity").hidden = true;
    select("#cabinetWait").hidden = true;
    select("#cabinetUnavailable").hidden = false;
    select("#cabinetMode").textContent = "UNAVAILABLE";
    select("#cabinetError").textContent = error || "Канонический paper runtime недоступен. Значения не подставляются.";
    const missing = "Канонический paper runtime недоступен. Значения не подставляются.";
    setTruth(select("#portfolioBody"), "unavailable", "UNAVAILABLE", missing);
    setTruth(select("#tradesBody"), "unavailable", "UNAVAILABLE", missing);
    setTruth(select("#marketBody"), "unavailable", "UNAVAILABLE", missing);
    setTruth(select("#riskBody"), "unavailable", "UNAVAILABLE", missing);
    setTruth(select("#systemBody"), "unavailable", "UNAVAILABLE", missing);
  }

  function renderNews(payload) {
    const body = select("#newsBody");
    if (!payload || payload.news_available !== true) {
      setTruth(body, "unavailable", "UNAVAILABLE", payload?.news_error || "Сохранённый список новостей недоступен. Новый сбор не запускается.");
      return;
    }
    const items = Array.isArray(payload.news) ? payload.news : [];
    if (!items.length) {
      setTruth(body, "empty", "Нет новостей", "Сохранённый список пуст. Демо-новости не подставляются.");
      return;
    }
    body.replaceChildren();
    const list = document.createElement("ul");
    list.className = "os-list";
    items.forEach((item) => {
      const li = document.createElement("li");
      const title = document.createElement("b");
      title.textContent = item && item.title ? String(item.title) : "без заголовка";
      const meta = document.createElement("small");
      const source = item && item.source ? String(item.source) : "источник не указан";
      const published = item && item.published_at ? String(item.published_at) : "время не указано";
      meta.textContent = `${source} · ${published}`;
      li.append(title, meta);
      list.append(li);
    });
    body.append(list);
  }

  function renderCabinet(payload) {
    renderNews(payload);
    if (!payload || payload.data_available !== true || payload.mode === "UNAVAILABLE") {
      showUnavailable(payload && payload.error);
      return;
    }
    select("#cabinetUnavailable").hidden = true;
    select("#cabinetMetrics").hidden = false;
    select("#cabinetActivity").hidden = false;
    select("#metricEquity").textContent = formatMoney(payload.equity);
    select("#metricCash").textContent = formatMoney(payload.cash);
    select("#metricNetPnl").textContent = formatMoney(payload.net_pnl);
    select("#metricRealized").textContent = formatMoney(payload.realized_pnl);
    select("#metricUnrealized").textContent = formatMoney(payload.unrealized_pnl);
    select("#metricPeak").textContent = formatMoney(payload.peak_equity);
    select("#metricFees").textContent = formatMoney(payload.total_fees);
    select("#metricPositions").textContent = formatCount(payload.open_positions);
    select("#metricTradeCount").textContent = formatCount(payload.trade_count);
    select("#metricWorker").textContent = payload.worker_running === true ? "running" : payload.worker_running === false ? "stopped" : "нет данных";
    select("#metricLastAction").textContent = payload.last_action || "нет данных";
    select("#metricLastReason").textContent = payload.last_reason || "нет данных";
    select("#metricPositionList").textContent = formatPositions(payload.positions);
    const hasWait = payload.wait === "WAIT" || (typeof payload.last_action === "string" && payload.last_action.toUpperCase() === "WAIT");
    const hasDrawdown = typeof payload.drawdown_percent === "number" && Number.isFinite(payload.drawdown_percent);
    if (hasWait || hasDrawdown) {
      select("#cabinetWait").hidden = false;
      select("#waitAction").textContent = hasWait ? "WAIT" : (payload.last_action || "");
      select("#waitReason").textContent = payload.last_reason || "";
      select("#waitDrawdown").textContent = hasDrawdown
        ? `Просадка: ${payload.drawdown_percent.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}%`
        : "";
    } else {
      select("#cabinetWait").hidden = true;
    }

    const positions = payload.positions;
    if (positions == null) {
      setTruth(select("#portfolioBody"), "unavailable", "UNAVAILABLE", "Позиции канонического paper недоступны.");
    } else {
      fillTable(
        select("#portfolioBody"),
        ["Инструмент", "Количество", "Вход", "Открыта", "Причина"],
        positionRows(positions),
        "Нет открытых позиций",
        "Открытых канонических позиций нет. Это не вымышленный ноль.",
      );
    }

    if (!Array.isArray(payload.trades) && payload.trades != null) {
      setTruth(select("#tradesBody"), "unavailable", "UNAVAILABLE", "Журнал сделок недоступен.");
    } else {
      fillTable(
        select("#tradesBody"),
        ["Время", "Инструмент", "Сторона", "Количество", "Цена", "Комиссия", "Net PnL", "Причина"],
        tradeRows(payload.trades || []),
        "Нет сделок",
        "Канонических сделок пока нет. Это не вымышленный ноль.",
      );
    }

    const symbols = collectSymbols(payload);
    const verified = payload.market_verified === true ? "подтверждён" : payload.market_verified === false ? "не подтверждён" : "нет данных";
    const age = typeof payload.market_age_seconds === "number" && Number.isFinite(payload.market_age_seconds)
      ? `${payload.market_age_seconds.toLocaleString("ru-RU")} с`
      : "нет данных";
    kvGrid(select("#marketBody"), [
      ["ВЕРИФИКАЦИЯ РЫНКА", verified],
      ["ВОЗРАСТ ПОТОКА", age],
      ["СИМВОЛЫ", symbols.length ? symbols.join(", ") : "нет символов из позиций и сделок"],
    ]);

    kvGrid(select("#riskBody"), [
      ["WAIT", payload.wait === "WAIT" ? "WAIT" : "нет"],
      ["ПОСЛЕДНЯЯ ПРИЧИНА", payload.last_reason || "нет данных"],
      ["ПРОСАДКА", hasDrawdown ? `${payload.drawdown_percent.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}%` : "нет данных"],
      ["КОМИССИИ", formatMoney(payload.total_fees)],
      ["ОТКРЫТЫЕ ПОЗИЦИИ", formatCount(payload.open_positions)],
    ]);

    kvGrid(select("#systemBody"), [
      ["РЕЖИМ", formatMode(payload)],
      ["ВОРКЕР", payload.worker_running === true ? "running" : payload.worker_running === false ? "stopped" : "нет данных"],
      ["DATABASE BACKED", payload.database_backed === true ? "да" : payload.database_backed === false ? "нет" : "нет данных"],
      ["SOURCE OF TRUTH", payload.source_of_truth || "нет данных"],
    ]);
  }

  async function loadCabinet() {
    try {
      const payload = await requestJson("/api/site-v1/cabinet");
      renderCabinet(payload);
    } catch {
      showUnavailable("Канонический paper runtime недоступен. Значения не подставляются.");
      renderNews({ news_available: false });
    }
  }

  async function loadWorkspace() {
    try {
      const session = await requestJson("/api/auth/me");
      if (!session.authenticated) {
        if (window.location.pathname === "/app") window.location.replace("/?mode=login&next=/app");
        return;
      }
      if (window.location.pathname === "/") {
        window.location.replace("/app");
        return;
      }
      accessView.hidden = true;
      workspaceView.hidden = false;
      select("#workspaceUser").textContent = session.user?.display_name || session.user?.email || "";
      ensureStubPanels();
      setOsPage(currentOsPage());
      await loadCabinet();
    } catch {
      if (window.location.pathname === "/app") window.location.replace("/?mode=login&next=/app");
    }
  }

  select("#logoutButton").addEventListener("click", async () => {
    const target = select("#workspaceMessage");
    setMessage("", "error", target);
    select("#logoutButton").disabled = true;
    try {
      await requestJson("/api/auth/logout", { method: "POST", body: "{}" });
      window.location.assign("/?mode=login");
    } catch {
      setMessage("Не удалось завершить сессию. Повторите попытку.", "error", target);
      select("#logoutButton").disabled = false;
    }
  });

  navButtons().forEach((button) => {
    button.addEventListener("click", () => setOsPage(button.dataset.osPage));
  });
  window.addEventListener("hashchange", () => {
    if (window.location.pathname === "/app") setOsPage(currentOsPage());
  });

  const initialMode = new URLSearchParams(window.location.search).get("mode");
  setMode(initialMode === "register" ? "register" : "login");
  ensureStubPanels();
  void loadWorkspace();
})();
