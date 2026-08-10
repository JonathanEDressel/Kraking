/**
 * Saved assistant conversations.
 *
 * Kept in localStorage rather than the database: it's the same machine either
 * way, but this keeps conversations out of the backup/report surface and means
 * no migration for something that is, in the end, a scratchpad. Scoped per
 * account — several people share one install via the accounts screen, and one
 * person's questions shouldn't show up in another's sidebar.
 */

interface AiConversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  turns: AiTurn[];
}

class AiHistory {
  private static readonly PREFIX = 'cyrus_ai_history_';
  /** Oldest conversations fall off past this. */
  private static readonly MAX_CONVERSATIONS = 30;

  private static key(): string | null {
    const user = AuthController.getUser();
    return user?.id ? `${AiHistory.PREFIX}${user.id}` : null;
  }

  static list(): AiConversation[] {
    const key = AiHistory.key();
    if (!key) return [];
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || '[]');
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter(c => c && typeof c.id === 'string' && Array.isArray(c.turns))
        .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    } catch {
      // Corrupt or hand-edited storage shouldn't take the panel down with it.
      return [];
    }
  }

  static get(id: string): AiConversation | null {
    return AiHistory.list().find(c => c.id === id) || null;
  }

  /** Insert or update, then trim. Returns the id so a new thread can adopt it. */
  static save(id: string | null, turns: AiTurn[]): string | null {
    const key = AiHistory.key();
    if (!key || turns.length === 0) return id;

    const now = Date.now();
    const conversations = AiHistory.list();
    const existing = id ? conversations.find(c => c.id === id) : null;

    if (existing) {
      existing.turns = turns;
      existing.updatedAt = now;
      // The title comes from the opening question, so it doesn't churn as the
      // conversation goes on.
    } else {
      id = `c${now.toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
      conversations.unshift({
        id,
        title: AiHistory.titleFrom(turns),
        createdAt: now,
        updatedAt: now,
        turns,
      });
    }

    AiHistory.write(key, conversations.slice(0, AiHistory.MAX_CONVERSATIONS));
    return id;
  }

  static remove(id: string): void {
    const key = AiHistory.key();
    if (!key) return;
    AiHistory.write(key, AiHistory.list().filter(c => c.id !== id));
  }

  static clear(): void {
    const key = AiHistory.key();
    if (key) localStorage.removeItem(key);
  }

  private static write(key: string, conversations: AiConversation[]): void {
    try {
      localStorage.setItem(key, JSON.stringify(conversations));
    } catch {
      // Quota exceeded — drop the oldest half and try once. Losing old
      // conversations is much better than losing the current one.
      try {
        localStorage.setItem(
          key, JSON.stringify(conversations.slice(0, Math.ceil(conversations.length / 2))));
      } catch {
        /* give up quietly; history is not load-bearing */
      }
    }
  }

  private static titleFrom(turns: AiTurn[]): string {
    const first = turns.find(t => t.role === 'user')?.content?.trim() || 'Conversation';
    const oneLine = first.replace(/\s+/g, ' ');
    return oneLine.length > 60 ? `${oneLine.slice(0, 57)}…` : oneLine;
  }

  /** "just now" / "14:32" / "Tue" / "3 Mar" — short enough for a list row. */
  static relativeTime(ts: number): string {
    const diff = Date.now() - ts;
    const date = new Date(ts);
    if (diff < 60_000) return 'just now';
    if (diff < 86_400_000) {
      return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    }
    if (diff < 7 * 86_400_000) return date.toLocaleDateString(undefined, { weekday: 'short' });
    return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }
}
