"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { LOGS_LIVE_URL, type LiveLogLine } from "@/lib/api";
import { fmtTimeMs } from "@/lib/format";
import { cn } from "@/lib/utils";
import { NoData } from "../common";
import { LevelChip } from "./level";

/** Буфер live-хвоста, строк. */
const LIVE_BUFFER_MAX = 5000;
/** Порог «у низа» для автопрокрутки, px. */
const AT_BOTTOM_PX = 40;

/**
 * Режим «Live-хвост» вкладки «Логи»: SSE GET /api/logs/live.
 * Автопрокрутка вниз; скролл вверх → пауза + кнопка «вниз/продолжить»;
 * буфер ≤5000 строк, дедупликация по ts+line.
 */
export function LogsLive() {
  const [lines, setLines] = useState<LiveLogLine[]>([]);
  const [connected, setConnected] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const boxRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const es = new EventSource(LOGS_LIVE_URL);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (ev: MessageEvent<string>) => {
      let l: LiveLogLine;
      try {
        l = JSON.parse(ev.data);
      } catch {
        return;
      }
      const key = `${l.ts}|${l.line}`;
      if (seenRef.current.has(key)) return;
      seenRef.current.add(key);
      if (seenRef.current.size > LIVE_BUFFER_MAX + 1000) seenRef.current = new Set();
      setLines((prev) => {
        const next = prev.length >= LIVE_BUFFER_MAX ? [...prev.slice(-LIVE_BUFFER_MAX + 1), l] : [...prev, l];
        return next;
      });
    };
    return () => es.close();
  }, []);

  const onScroll = useCallback(() => {
    const el = boxRef.current;
    if (el == null) return;
    const at = el.scrollHeight - el.scrollTop - el.clientHeight < AT_BOTTOM_PX;
    atBottomRef.current = at;
    setAtBottom(at);
  }, []);

  // автопрокрутка, только пока пользователь у низа
  useLayoutEffect(() => {
    if (!atBottomRef.current) return;
    const el = boxRef.current;
    if (el != null) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const scrollToBottom = useCallback(() => {
    const el = boxRef.current;
    if (el != null) el.scrollTop = el.scrollHeight;
    atBottomRef.current = true;
    setAtBottom(true);
  }, []);

  return (
    <div className="relative">
      <div
        ref={boxRef}
        onScroll={onScroll}
        className="h-[560px] overflow-y-auto rounded-xl border border-line bg-panel px-3 py-2 font-mono text-xs leading-5"
      >
        {lines.length === 0 ? (
          <NoData
            text={
              connected
                ? "Ожидаем новые строки лога…"
                : "Подключение к SSE /api/logs/live…"
            }
          />
        ) : (
          lines.map((l, i) => (
            <div key={`${l.ts}|${i}`} className="flex gap-2 py-px hover:bg-panel2/40">
              <span className="shrink-0 tabular-nums text-muted">{fmtTimeMs(l.ts)}</span>
              <LevelChip level={l.level} />
              <span className="shrink-0 text-muted">[{l.source}]</span>
              <span className="whitespace-pre-wrap break-words">{l.line}</span>
            </div>
          ))
        )}
      </div>
      <div className="mt-1 flex items-center justify-between text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span
            className={cn(
              "inline-block h-2 w-2 rounded-full",
              connected ? "bg-emerald-400" : "bg-red-400",
            )}
          />
          {connected ? "SSE подключён" : "SSE: переподключение…"}
          <span className="tabular-nums">· {lines.length} строк в буфере</span>
        </span>
        {!atBottom && lines.length > 0 && (
          <button
            type="button"
            onClick={scrollToBottom}
            className="rounded-md border border-accent/40 bg-accent/10 px-2 py-1 text-accent hover:bg-accent/20"
          >
            ↓ вниз (продолжить)
          </button>
        )}
      </div>
    </div>
  );
}
