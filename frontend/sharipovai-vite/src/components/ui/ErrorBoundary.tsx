import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("SharipovAI frontend boundary", {
      name: error.name,
      componentStack: info.componentStack,
    });
  }

  private reload = () => window.location.reload();

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children;

    return (
      <main className="grid min-h-screen place-items-center p-6">
        <section
          className="w-full max-w-lg rounded-3xl border border-rose-400/30 bg-slate-950/80 p-8 shadow-2xl"
          role="alert"
          aria-labelledby="fatal-error-title"
        >
          <AlertTriangle className="mb-5 size-10 text-rose-300" aria-hidden="true" />
          <h1 id="fatal-error-title" className="text-2xl font-semibold text-white">
            Интерфейс временно недоступен
          </h1>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            Ошибка изолирована. Перезагрузите приложение; API-ключи и технические детали
            пользователю не показываются.
          </p>
          <button className="primary-button mt-6" type="button" onClick={this.reload}>
            <RotateCcw className="size-4" aria-hidden="true" />
            Перезагрузить
          </button>
        </section>
      </main>
    );
  }
}
