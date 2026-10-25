import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ChatSessionProvider } from "./context/ChatSessionContext";
import { AppHeader } from "./components/layout/AppHeader";
import { NavBar } from "./components/layout/NavBar";
import { DashboardPage } from "./pages/DashboardPage";
import { ChatPage } from "./pages/ChatPage";

/** Top-level app: providers, shell chrome, and route table. */
export function App() {
  return (
    <ChatSessionProvider>
      <BrowserRouter>
        <main>
          <AppHeader />
          <NavBar />
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/chat" element={<ChatPage />} />
          </Routes>
        </main>
      </BrowserRouter>
    </ChatSessionProvider>
  );
}
