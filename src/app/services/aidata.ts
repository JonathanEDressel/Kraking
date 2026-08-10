// Portfolio assistant API client.

interface AiStatus {
  configured: boolean;
  model: string;
}

/** One action the model wants to take, described from its parsed arguments. */
interface AiAction {
  tool: string;
  title: string;
  detail: string;
  danger: boolean;
}

interface AiPending {
  token: string;
  actions: AiAction[];
}

/** The outcome of an action the user approved (or declined). */
interface AiResult {
  title: string;
  detail: string;
  ok: boolean;
  declined: boolean;
  error: string | null;
}

interface AiReply {
  answer: string;
  /** Set when the model is waiting on a confirmation before it can continue. */
  pending: AiPending | null;
  results: AiResult[];
}

interface AiTurn {
  role: 'user' | 'assistant';
  content: string;
  /** Display-only; stripped before the turn is replayed to the model. */
  results?: AiResult[];
}

class AiData {
  static async getStatus(token: string): Promise<ApiResponse<AiStatus>> {
    return DataAccess.get<AiStatus>(`${AppConfig.API_BASE}/ai/status`, token);
  }

  static async saveKey(apiKey: string, token: string): Promise<ApiResponse<AiStatus>> {
    return DataAccess.put(`${AppConfig.API_BASE}/ai/key`, { api_key: apiKey }, token);
  }

  static async deleteKey(token: string): Promise<ApiResponse<AiStatus>> {
    return DataAccess.del(`${AppConfig.API_BASE}/ai/key`, token);
  }

  /**
   * `history` is the visible conversation, replayed so follow-ups keep context.
   * Portfolio data is never sent — the backend gathers it itself.
   */
  static async ask(
    question: string,
    history: AiTurn[],
    refresh: boolean,
    token: string
  ): Promise<ApiResponse<AiReply>> {
    return DataAccess.post(
      `${AppConfig.API_BASE}/ai/ask`,
      // Strip the display-only fields: the model replays what it said, not
      // the status rows the panel drew underneath it.
      { question, history: history.map(t => ({ role: t.role, content: t.content })), refresh },
      token
    );
  }

  /** Approve or decline the actions a paused turn is waiting on. Nothing that
   *  changes state has run until this resolves. */
  static async confirm(
    pendingToken: string,
    approved: boolean,
    token: string
  ): Promise<ApiResponse<AiReply>> {
    return DataAccess.post(
      `${AppConfig.API_BASE}/ai/confirm`,
      { token: pendingToken, approved },
      token
    );
  }
}
