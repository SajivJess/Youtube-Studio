import { Component, StrictMode, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppStateProvider } from "./appstate";
import { I18nProvider } from "./i18n";
import { JobsProvider } from "./jobs";
import { LanGate } from "./components/LanAccess";
import { MetaProvider } from "./meta";
import { ToastProvider } from "./toast";
import { UiModeProvider } from "./uimode";
import "./styles.css";
import "./easy.css";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("LEONIDEX UI Caught Error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, background: "#0a0d14", color: "#f1f5f9", minHeight: "100vh", fontFamily: "sans-serif" }}>
          <h1 style={{ color: "#ef4444" }}>🎮 LEONIDEX Encountered an Interface Error</h1>
          <p style={{ color: "#94a3b8" }}>{this.state.error?.message || "An unexpected error occurred while rendering the page."}</p>
          <pre style={{ background: "#111827", padding: 16, borderRadius: 8, overflowX: "auto", color: "#e2e8f0", fontSize: 13 }}>
            {this.state.error?.stack}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{ marginTop: 20, padding: "10px 20px", background: "#3b82f6", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontWeight: 600 }}
          >
            Reload LEONIDEX
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <I18nProvider>
        <LanGate>
          <MetaProvider>
            <ToastProvider>
              <JobsProvider>
                <AppStateProvider>
                  <UiModeProvider>
                    <App />
                  </UiModeProvider>
                </AppStateProvider>
              </JobsProvider>
            </ToastProvider>
          </MetaProvider>
        </LanGate>
      </I18nProvider>
    </ErrorBoundary>
  </StrictMode>,
);
