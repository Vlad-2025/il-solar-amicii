// Parse notes (warnings, arithmetic checks, OCR confidence) come back only with the upload response;
// keep them in memory so the bill screen can show them right after the upload.
export type DraftNotes = { warnings: string[]; validation: { ok: boolean; message: string }[]; ocr_confidence?: number | null };

const notes = new Map<number, DraftNotes>();

export function rememberDraft(id: number, n: DraftNotes) {
  notes.set(id, n);
}

export function draftNotes(id: number): DraftNotes | undefined {
  return notes.get(id);
}
