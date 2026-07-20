import { useEffect, useState } from "react";

export type ThemePreference = "dark" | "light" | "system";

const STORAGE_KEY = "sharipovai.theme";

function initialTheme(): ThemePreference {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "dark" || stored === "light" || stored === "system"
    ? stored
    : "system";
}

export function useTheme() {
  const [theme, setTheme] = useState<ThemePreference>(initialTheme);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");

    const applyTheme = () => {
      const dark = theme === "dark" || (theme === "system" && media.matches);
      document.documentElement.classList.toggle("dark", dark);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
      document.documentElement.style.colorScheme = dark ? "dark" : "light";
    };

    applyTheme();
    media.addEventListener("change", applyTheme);
    localStorage.setItem(STORAGE_KEY, theme);

    return () => media.removeEventListener("change", applyTheme);
  }, [theme]);

  return { theme, setTheme } as const;
}
