"use client";

import { useEffect, useState } from "react";
import { BellRing, RotateCcw, Save, Send } from "lucide-react";
import {
  ALERTS_SETTINGS_URL,
  ALERTS_URL,
  fetchJson,
  putAlertsSettings,
  testAlerts,
  usePoll,
  type AlertRule,
  type AlertsData,
  type AlertsSettings,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { fmtAgo, fmtTimeS } from "@/lib/format";
import { useRefresh } from "@/lib/refresh";
import { ErrorBanner, InfoBanner } from "../common";
import { cn } from "@/lib/utils";

function levelBadge(level: string) {
  return (
    <Badge variant={level === "critical" ? "destructive" : "warning"}>
      {level === "critical" ? "критич." : "warning"}
    </Badge>
  );
}

/** Активные алерты — карточки. */
function ActiveAlerts({ data }: { data: AlertsData }) {
  if (data.active.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-line bg-panel p-4 text-sm text-muted">
        <BellRing className="size-4 text-emerald-400" />
        Активных алертов нет
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {data.active.map((a) => {
        const rule = data.recent.find((r) => r.rule === a.rule);
        return (
          <div
            key={a.rule}
            className={cn(
              "flex items-start gap-3 rounded-xl border p-3",
              rule?.level === "critical"
                ? "border-red-500/40 bg-red-500/10"
                : "border-amber-500/40 bg-amber-500/10",
            )}
          >
            {levelBadge(rule?.level ?? "warning")}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{rule?.message ?? a.rule}</div>
              <div className="mt-0.5 text-xs text-muted">
                {a.rule} · {fmtAgo(a.triggered_at)}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Настройки: вкл/выкл, webhook + тест, правила. */
function AlertsSettingsCard() {
  const [settings, setSettings] = useState<AlertsSettings | null>(null);
  const [draft, setDraft] = useState<AlertsSettings | null>(null);
  const [webhook, setWebhook] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState<null | "save" | "test" | "reset">(null);
  const [status, setStatus] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (settings && !draft) {
      setDraft(settings);
      setWebhook(settings.telegram_webhook);
      setEnabled(settings.enabled);
    }
  }, [settings, draft]);

  const load = () =>
    fetchJson<AlertsSettings>(ALERTS_SETTINGS_URL)
      .then(setSettings)
      .catch((e: unknown) =>
        setStatus({ kind: "err", text: e instanceof Error ? e.message : "Ошибка API" }),
      );
  const [tick, setTick] = useState(0);
  const { tick: refreshTick } = useRefresh();
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, refreshTick]);

  const patchRule = (id: string, patch: Partial<AlertRule>) =>
    setDraft((d) =>
      d
        ? { ...d, rules: d.rules.map((r) => (r.id === id ? { ...r, ...patch } : r)) }
        : d,
    );

  const save = async () => {
    if (!draft) return;
    setBusy("save");
    setStatus(null);
    try {
      await putAlertsSettings({
        enabled,
        telegram_webhook: webhook.trim() || null,
        rules: draft.rules,
      });
      setDraft(null);
      setTick((t) => t + 1);
      setStatus({ kind: "ok", text: "Сохранено" });
    } catch (e: unknown) {
      setStatus({ kind: "err", text: e instanceof Error ? e.message : "Ошибка API" });
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    if (!draft) return;
    setBusy("reset");
    setStatus(null);
    try {
      await putAlertsSettings({ reset_rules: true });
      setDraft(null);
      setTick((t) => t + 1);
      setStatus({ kind: "ok", text: "Правила сброшены к значениям по умолчанию" });
    } catch (e: unknown) {
      setStatus({ kind: "err", text: e instanceof Error ? e.message : "Ошибка API" });
    } finally {
      setBusy(null);
    }
  };

  const sendTest = async () => {
    setBusy("test");
    setStatus(null);
    try {
      const r = await testAlerts();
      setStatus({ kind: "ok", text: r.message });
    } catch (e: unknown) {
      setStatus({
        kind: "err",
        text: e instanceof Error ? e.message : "Не удалось отправить",
      });
    } finally {
      setBusy(null);
    }
  };

  if (!settings || !draft) {
    return (
      <div className="rounded-xl border border-line bg-panel p-4 text-sm text-muted">
        Загрузка настроек…
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-line bg-panel p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium">Настройки алертов</div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted">Уведомления</span>
          <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Уведомления" />
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input
          value={webhook}
          onChange={(e) => setWebhook(e.target.value)}
          placeholder="https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT>"
          className="min-w-72 flex-1"
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={sendTest}
          disabled={busy != null}
          className="gap-1.5"
        >
          <Send className="size-3.5" />
          Тест
        </Button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-1 pr-2 font-normal">Вкл</th>
              <th className="py-1 pr-2 font-normal">Правило</th>
              <th className="py-1 pr-2 font-normal">Уровень</th>
              <th className="py-1 pr-2 font-normal">Условие</th>
              <th className="py-1 pr-2 font-normal">Порог</th>
              <th className="py-1 pr-2 font-normal">Длится, с</th>
              <th className="py-1 font-normal">Пауза, с</th>
            </tr>
          </thead>
          <tbody>
            {draft.rules.map((r) => (
              <tr key={r.id} className="border-t border-line">
                <td className="py-1.5 pr-2">
                  <Switch
                    size="sm"
                    checked={r.enabled}
                    onCheckedChange={(v) => patchRule(r.id, { enabled: v })}
                    aria-label={r.title}
                  />
                </td>
                <td className="py-1.5 pr-2">
                  <div className="text-foreground">{r.title}</div>
                  <div className="text-xs text-muted">{r.id}</div>
                </td>
                <td className="py-1.5 pr-2">
                  <Select
                    value={r.level}
                    onChange={(e) =>
                      patchRule(r.id, { level: e.target.value as AlertRule["level"] })
                    }
                    className="w-28"
                  >
                    <option value="warning">warning</option>
                    <option value="critical">critical</option>
                  </Select>
                </td>
                <td className="py-1.5 pr-2 text-xs text-muted">
                  {r.source ? (
                    <span>источник {r.source} — оффлайн</span>
                  ) : r.metric ? (
                    <span>
                      {r.metric} {r.op} …
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="py-1.5 pr-2">
                  {r.metric != null ? (
                    <Input
                      type="number"
                      size="sm"
                      value={r.value ?? ""}
                      onChange={(e) =>
                        patchRule(r.id, {
                          value: e.target.value === "" ? null : Number(e.target.value),
                        })
                      }
                      className="w-24"
                    />
                  ) : (
                    <span className="text-xs text-muted">—</span>
                  )}
                </td>
                <td className="py-1.5 pr-2">
                  <Input
                    type="number"
                    size="sm"
                    value={r.for_s}
                    onChange={(e) =>
                      patchRule(r.id, { for_s: Math.max(0, Number(e.target.value) || 0) })
                    }
                    className="w-20"
                  />
                </td>
                <td className="py-1.5">
                  <Input
                    type="number"
                    size="sm"
                    value={r.cooldown_s}
                    onChange={(e) =>
                      patchRule(r.id, { cooldown_s: Math.max(0, Number(e.target.value) || 0) })
                    }
                    className="w-24"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={save} disabled={busy != null} className="gap-1.5">
          <Save className="size-3.5" />
          Сохранить
        </Button>
        <Button variant="outline" size="sm" onClick={reset} disabled={busy != null} className="gap-1.5">
          <RotateCcw className="size-3.5" />
          Сбросить правила
        </Button>
        {status && (
          <span
            className={cn(
              "text-xs",
              status.kind === "ok" ? "text-emerald-400" : "text-red-400",
            )}
          >
            {status.text}
          </span>
        )}
      </div>
    </div>
  );
}

/** Журнал событий. */
function AlertsJournal({ data }: { data: AlertsData }) {
  if (data.recent.length === 0) {
    return (
      <div className="rounded-xl border border-line bg-panel p-4 text-sm text-muted">
        Журнал пуст — событий ещё не было
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-panel">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="px-3 py-2 font-normal">Время</th>
            <th className="px-3 py-2 font-normal">Правило</th>
            <th className="px-3 py-2 font-normal">Уровень</th>
            <th className="px-3 py-2 font-normal">Статус</th>
            <th className="px-3 py-2 font-normal">Сообщение</th>
            <th className="px-3 py-2 font-normal">Восстановлено</th>
          </tr>
        </thead>
        <tbody>
          {data.recent.map((r) => (
            <tr key={r.id} className="border-t border-line">
              <td className="whitespace-nowrap px-3 py-1.5 tabular-nums text-muted">
                {fmtTimeS(r.triggered_at)}
              </td>
              <td className="whitespace-nowrap px-3 py-1.5 text-muted">{r.rule}</td>
              <td className="px-3 py-1.5">{levelBadge(r.level)}</td>
              <td className="px-3 py-1.5">
                <Badge variant={r.status === "active" ? "destructive" : "outline"}>
                  {r.status === "active" ? "активен" : "закрыт"}
                </Badge>
              </td>
              <td className="max-w-md truncate px-3 py-1.5" title={r.message}>
                {r.message}
              </td>
              <td className="whitespace-nowrap px-3 py-1.5 tabular-nums text-muted">
                {r.resolved_at != null ? fmtTimeS(r.resolved_at) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Вкладка «Алерты» (F4.1): активные + настройки + журнал. */
export function AlertsTab() {
  const { data, loading, error } = usePoll<AlertsData>(ALERTS_URL, 15_000);

  return (
    <div className="space-y-3">
      {error != null && <ErrorBanner message={error} />}
      {!data && !loading && (
        <InfoBanner message="Нет данных (бэк оффлайн?)." />
      )}
      {data != null ? (
        <>
          <h2 className="text-sm font-medium text-muted">Активные алерты</h2>
          <ActiveAlerts data={data} />
          <AlertsSettingsCard />
          <h2 className="pt-1 text-sm font-medium text-muted">Журнал (последние 100)</h2>
          <AlertsJournal data={data} />
        </>
      ) : (
        <div className="h-40 animate-pulse rounded-xl border border-line bg-panel2" />
      )}
    </div>
  );
}
