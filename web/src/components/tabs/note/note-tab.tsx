"use client";

import { useCallback, useEffect, useState } from "react";
import {
  NOTE_URL,
  fetchJson,
  putJson,
  type NoteData,
  type NoteSaved,
} from "@/lib/api";
import { fmtAgo } from "@/lib/format";
import { mdToHtml } from "@/lib/markdown";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ErrorBanner } from "@/components/tabs/common";

type Mode = "view" | "edit";

function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-lg border border-line bg-panel p-0.5">
      {(
        [
          ["view", "Просмотр"],
          ["edit", "Редактирование"],
        ] as [Mode, string][]
      ).map(([m, label]) => (
        <button
          key={m}
          type="button"
          onClick={() => onChange(m)}
          className={cn(
            "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
            mode === m ? "bg-accent/15 text-accent" : "text-muted hover:text-foreground",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/**
 * Вкладка «Note»: один markdown-файл в каталоге проекта (api: NOTE_PATH,
 * по умолчанию note.md рядом с БД — в docker это bind ./data). Загрузка при
 * входе, правка в textarea, «Сохранить» (PUT, файл перезаписывается) →
 * превью markdown.
 */
export function NoteTab() {
  const [savedText, setSavedText] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [mtime, setMtime] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("view");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await fetchJson<NoteData>(NOTE_URL);
      setSavedText(d.content);
      setText(d.content);
      setMtime(d.mtime);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить заметку");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const dirty = savedText != null && text !== savedText;

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const r = await putJson<NoteSaved>(NOTE_URL, { content: text });
      setSavedText(text);
      setMtime(r.mtime);
      setMode("view"); // после сохранения — превью markdown
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить заметку");
    } finally {
      setSaving(false);
    }
  }, [text]);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <ModeToggle mode={mode} onChange={setMode} />
        <div className="flex items-center gap-2">
          {mtime != null && (
            <span className="text-xs text-muted" title="Последнее изменение файла">
              изменён {fmtAgo(mtime)}
            </span>
          )}
          {mode === "edit" && (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setText(savedText ?? "");
                  setMode("view");
                }}
                disabled={saving || !dirty}
              >
                Отменить
              </Button>
              <Button size="sm" onClick={save} disabled={saving || !dirty}>
                {saving ? "Сохранение…" : "Сохранить"}
              </Button>
            </>
          )}
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      {!loaded ? (
        <p className="text-sm text-muted">Загрузка…</p>
      ) : mode === "edit" ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          className="h-[65vh] w-full resize-y rounded-xl border border-line bg-panel p-3 font-mono text-sm leading-relaxed outline-none focus:border-accent/50"
          aria-label="Текст заметки (markdown)"
        />
      ) : savedText ? (
        <div className="max-w-3xl space-y-1 text-sm">
          <div dangerouslySetInnerHTML={{ __html: mdToHtml(savedText) }} />
        </div>
      ) : error != null ? null : (
        <p className="text-sm text-muted">
          Заметка пуста. Нажмите «Редактирование», запишите что-нибудь в
          markdown и сохраните.
        </p>
      )}
    </div>
  );
}
