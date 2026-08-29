import { useEffect } from "react";
import { Header } from "./components/Header";
import { Modal } from "./components/Modal";
import { SettingsTab } from "./tabs/SettingsTab";
import { SlaveTab } from "./tabs/SlaveTab";
import { MasterTab } from "./tabs/MasterTab";
import { ScenarioTab } from "./tabs/ScenarioTab";
import { LogTab } from "./tabs/LogTab";
import { useStore, type TabKey } from "./store";

const TABS: { key: TabKey; label: string }[] = [
  { key: "settings", label: "通信設定" },
  { key: "tcp", label: "TCP スレーブ" },
  { key: "rtu", label: "RTU スレーブ" },
  { key: "master", label: "マスター" },
  { key: "scenario", label: "シナリオ" },
  { key: "log", label: "通信ログ" },
];

export default function App() {
  const { activeTab, setActiveTab, connect, connected, error, confirmState, resolveConfirm } =
    useStore();

  useEffect(() => {
    connect();
  }, [connect]);

  return (
    <div className="app">
      <Header />
      {error && (
        <div className="err" onClick={() => useStore.getState().setError(null)}>
          {error} <span className="muted">(クリックで消去)</span>
        </div>
      )}
      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={activeTab === t.key ? "active" : ""}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
        {!connected && <span className="conn-lost" style={{ marginLeft: "auto", alignSelf: "center" }}>● 未接続（再接続中…）</span>}
      </div>
      <div className="content">
        {activeTab === "settings" && <SettingsTab />}
        {activeTab === "tcp" && <SlaveTab mode="tcp" />}
        {activeTab === "rtu" && <SlaveTab mode="rtu" />}
        {activeTab === "master" && <MasterTab />}
        {activeTab === "scenario" && <ScenarioTab />}
        {activeTab === "log" && <LogTab />}
      </div>
      {confirmState && (
        <Modal
          title="確認"
          onClose={() => resolveConfirm(false)}
          onOk={() => resolveConfirm(true)}
          okLabel="OK"
        >
          <p style={{ whiteSpace: "pre-wrap" }}>{confirmState.message}</p>
        </Modal>
      )}
    </div>
  );
}
