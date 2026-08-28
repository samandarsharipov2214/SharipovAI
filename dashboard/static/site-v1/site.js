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
    const buttonText = form.querySelector(".primary-action span");
    if (busy) {
      buttonText.dataset.original = buttonText.textContent;
      buttonText.textContent = label;
    } else if (buttonText.dataset.original) {
      buttonText.textContent = buttonText.dataset.original;
      delete buttonText.dataset.original;
    }
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error("request_failed");
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

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
    if (!validate(forms.login)) return;
    setMessage();
    setBusy(forms.login, true);
    const values = Object.fromEntries(new FormData(forms.login));
    try {
      await requestJson("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: values.email, password: values.password }),
      });
      window.location.assign("/app");
    } catch (error) {
      const status = error.payload?.detail?.status;
      setMessage(status === "pending_approval"
        ? "Заявка ещё ожидает одобрения администратора."
        : "Не удалось войти. Проверьте e-mail и пароль.");
      setBusy(forms.login, false);
    }
  });

  forms.register.addEventListener("submit", async (event) => {
    event.preventDefault();
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
      setMessage(status === "already_exists"
        ? "Аккаунт с таким e-mail уже существует."
        : "Проверьте заполненные поля и повторите попытку.");
    } finally {
      setBusy(forms.register, false);
    }
  });

  async function loadWorkspace() {
    if (window.location.pathname !== "/app") return;
    try {
      const session = await requestJson("/api/auth/me");
      if (!session.authenticated) {
        window.location.replace("/?mode=login&next=/app");
        return;
      }
      accessView.hidden = true;
      workspaceView.hidden = false;
      select("#workspaceUser").textContent = session.user?.display_name || session.user?.email || "";
    } catch {
      window.location.replace("/?mode=login&next=/app");
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
