"use client";

import { NoteTab } from "@/components/tabs/note/note-tab";

/** Вкладка «Note»: markdown-заметка (файл в каталоге проекта, api /api/note). */
export default function NotePage() {
  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Note</h1>
      <NoteTab />
    </div>
  );
}
