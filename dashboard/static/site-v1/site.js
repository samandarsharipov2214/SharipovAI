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

  function showUnavailable(error) {
    select("#cabinetMetrics").hidden = true;
    select("#cabinetActivity").hidden = true;
    select("#cabinetWait").hidden = true;
    select("#cabinetUnavailable").hidden = false;
    select("#cabinetMode").textContent = "UNAVAILABLE";
    select("#cabinetError").textContent = error || "Канонический paper runtime недоступен. Значения не подставляются.";
  }

  function renderCabinet(payload) {
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
    select("#metricFees").textContent = formatMoney(payload.total_fees);
    select("#metricPositions").textContent = formatCount(payload.open_positions);
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
  }

  async function loadCabinet() {
    try {
      const payload = await requestJson("/api/site-v1/cabinet");
      renderCabinet(payload);
    } catch {
      showUnavailable("Канонический paper runtime недоступен. Значения не подставляются.");
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

  const initialMode = new URLSearchParams(window.location.search).get("mode");
  setMode(initialMode === "register" ? "register" : "login");
  void loadWorkspace();
})();
