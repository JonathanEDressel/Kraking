/**
 * API client for exchange transfer history (deposits and withdrawals).
 *
 * Reads are cheap — the backend serves them from its own table and never calls
 * an exchange. `sync` is the expensive one, and it deliberately does only a
 * bounded slice of work per call: a `complete: false` reply means "call me
 * again", not "something failed".
 */
class TransferData {
  static async list(token: string, filters: TransferFilters = {}): Promise<ApiResponse<TransferPage>> {
    const params = new URLSearchParams();
    if (filters.connId !== undefined && filters.connId !== null) params.set('conn_id', String(filters.connId));
    if (filters.kind) params.set('kind', filters.kind);
    if (filters.asset) params.set('asset', filters.asset);
    if (filters.status) params.set('status', filters.status);
    if (filters.from !== undefined) params.set('from', String(filters.from));
    if (filters.to !== undefined) params.set('to', String(filters.to));
    if (filters.limit !== undefined) params.set('limit', String(filters.limit));
    if (filters.offset !== undefined) params.set('offset', String(filters.offset));
    const query = params.toString();
    return DataAccess.get<TransferPage>(
      `${AppConfig.API_BASE}/transfers/${query ? `?${query}` : ''}`,
      token
    );
  }

  static async status(token: string): Promise<ApiResponse<TransferSyncStatus>> {
    return DataAccess.get<TransferSyncStatus>(`${AppConfig.API_BASE}/transfers/status`, token);
  }

  static async sync(token: string, connId?: number | 'all'): Promise<ApiResponse<TransferSyncResult>> {
    const body = connId === undefined || connId === 'all' ? {} : { conn_id: connId };
    return DataAccess.post<TransferSyncResult>(`${AppConfig.API_BASE}/transfers/sync`, body, token);
  }

  static async assets(token: string): Promise<ApiResponse<string[]>> {
    return DataAccess.get<string[]>(`${AppConfig.API_BASE}/transfers/assets`, token);
  }

  /** Date-ordered movements: what left where, and where it landed. */
  static async flow(token: string, asset?: string): Promise<ApiResponse<TransferFlow>> {
    const params = new URLSearchParams();
    if (asset) params.set('asset', asset);
    const query = params.toString();
    return DataAccess.get<TransferFlow>(
      `${AppConfig.API_BASE}/transfers/flow${query ? `?${query}` : ''}`, token);
  }

  static async rematch(token: string): Promise<ApiResponse<MatchSummary>> {
    return DataAccess.post<MatchSummary>(`${AppConfig.API_BASE}/transfers/rematch`, {}, token);
  }

  static async confirmMatch(token: string, withdrawalId: number,
                            depositId: number): Promise<ApiResponse<null>> {
    return DataAccess.post<null>(`${AppConfig.API_BASE}/transfers/match/confirm`,
      { withdrawal_id: withdrawalId, deposit_id: depositId }, token);
  }

  static async rejectMatch(token: string, withdrawalId: number,
                           depositId: number): Promise<ApiResponse<null>> {
    return DataAccess.post<null>(`${AppConfig.API_BASE}/transfers/match/reject`,
      { withdrawal_id: withdrawalId, deposit_id: depositId }, token);
  }

  static async unlockMatch(token: string, transferId: number): Promise<ApiResponse<null>> {
    return DataAccess.post<null>(`${AppConfig.API_BASE}/transfers/match/unlock`,
      { transfer_id: transferId }, token);
  }
}

/** Tracked crypto addresses — the only way a one-legged transfer gets a name. */
class WalletData {
  static async list(token: string): Promise<ApiResponse<TrackedWallet[]>> {
    return DataAccess.get<TrackedWallet[]>(`${AppConfig.API_BASE}/wallets/`, token);
  }

  static async suggestions(token: string): Promise<ApiResponse<WalletSuggestion[]>> {
    return DataAccess.get<WalletSuggestion[]>(`${AppConfig.API_BASE}/wallets/suggestions`, token);
  }

  static async create(token: string, body: WalletInput): Promise<ApiResponse<WalletWriteResult>> {
    return DataAccess.post<WalletWriteResult>(`${AppConfig.API_BASE}/wallets/`, body, token);
  }

  static async update(token: string, id: number,
                      body: WalletInput): Promise<ApiResponse<WalletWriteResult>> {
    return DataAccess.put<WalletWriteResult>(`${AppConfig.API_BASE}/wallets/${id}`, body, token);
  }

  static async remove(token: string, id: number): Promise<ApiResponse<{ match: MatchSummary }>> {
    return DataAccess.del<{ match: MatchSummary }>(`${AppConfig.API_BASE}/wallets/${id}`, token);
  }

  /** The .xlsx template, base64-encoded. `includeExisting` exports what's saved. */
  static async template(token: string,
                        includeExisting = false): Promise<ApiResponse<WalletTemplate>> {
    const query = includeExisting ? '?include_existing=1' : '';
    return DataAccess.get<WalletTemplate>(
      `${AppConfig.API_BASE}/wallets/template${query}`, token);
  }

  static async importFile(token: string, filename: string, base64: string,
                          preview: boolean): Promise<ApiResponse<WalletImportResult>> {
    return DataAccess.post<WalletImportResult>(`${AppConfig.API_BASE}/wallets/import`,
      { filename, content_base64: base64, preview }, token);
  }
}

interface WalletTemplate {
  filename: string;
  content_base64: string;
  bytes: number;
  /** How many existing wallets were written into it (0 for the blank template). */
  exported: number;
}

interface WalletImportRowError {
  row: number | null;
  label?: string;
  address?: string;
  message: string;
}

interface WalletImportResult {
  preview: boolean;
  header_row: number | null;
  unknown_columns: string[];
  would_create: Array<{
    row: number; label: string; address: string;
    chain: string | null; is_own: boolean;
  }>;
  created: number;
  duplicates: Array<{
    row: number; label: string; address: string; existing_label: string;
  }>;
  errors: WalletImportRowError[];
  warnings: WalletImportRowError[];
  match: MatchSummary | null;
}

interface MatchSummary {
  linked: number;
  suggested: number;
  wallet_resolved: number;
  unresolved: number;
  matched_at?: number;
}

/** One end of a movement. `unknown` means exactly that — never a guess. */
interface FlowEndpoint {
  type: 'exchange' | 'wallet' | 'unknown';
  label: string;
  exchange?: string;
  connection_id?: number;
  wallet_id?: number;
  is_own?: boolean;
  address?: string | null;
}

interface FlowSuggestion {
  transfer_id: number;
  exchange: string;
  kind: 'deposit' | 'withdrawal';
  amount: string;
  asset: string;
  occurred_at: number;
  confidence: number | null;
  withdrawal_id: number;
  deposit_id: number;
}

interface FlowHop {
  occurred_at: number;
  asset: string;
  amount: string;
  amount_num: number;
  from: FlowEndpoint;
  to: FlowEndpoint;
  legs: number[];
  /** internal = both ends known and paired; outbound/inbound = one leg only. */
  kind: 'internal' | 'outbound' | 'inbound';
  match_source: string | null;
  confidence: number | null;
  locked?: boolean;
  status?: string | null;
  is_internal?: number | null;
  /** Present on internal hops. */
  received?: string;
  received_num?: number;
  network_fee?: number | null;
  arrived_at?: number;
  /** Present on unpaired legs the matcher has a candidate for. */
  suggestion?: FlowSuggestion | null;
  fee_amount?: string | null;
  fee_currency?: string | null;
}

interface TransferFlow {
  hops: FlowHop[];
  counts: Record<string, number>;
  total_legs: number;
}

interface TrackedWallet {
  id: number;
  label: string;
  address: string;
  chain: string | null;
  asset: string | null;
  /** Stellar memo / XRP destination tag. Stored for reference; matching is on
   *  the address, since that is all an exchange reports for a counterparty. */
  tag: string | null;
  is_own: boolean;
  notes: string | null;
  transfer_count: number;
  created_at?: string;
}

interface WalletSuggestion {
  address: string;
  network: string | null;
  assets: string[];
  uses: number;
  withdrawals: number;
  deposits: number;
  last_seen: number;
}

interface WalletInput {
  label: string;
  address: string;
  chain?: string | null;
  tag?: string | null;
  asset?: string | null;
  is_own?: boolean;
  notes?: string | null;
}

interface WalletWriteResult {
  wallet: TrackedWallet;
  match: MatchSummary;
}

interface TransferFilters {
  connId?: number | 'all' | null;
  kind?: 'deposit' | 'withdrawal';
  asset?: string;
  status?: string;
  from?: number;
  to?: number;
  limit?: number;
  offset?: number;
}

interface TransferRow {
  id: number;
  exchange_connection_id: number;
  exchange_name: string;
  exchange_label: string | null;
  kind: 'deposit' | 'withdrawal';
  external_id: string | null;
  txid: string | null;
  network: string | null;
  asset: string;
  /** Exact decimal as text — the display and precision source of truth. */
  amount: string;
  /** Float mirror of `amount`, for sorting only. */
  amount_num: number;
  fee_amount: string | null;
  fee_currency: string | null;
  status: string | null;
  address: string | null;
  tag: string | null;
  /** Epoch SECONDS, not milliseconds. */
  occurred_at: number;
  usd_value: number | null;
  /** null = unknown, 0 = external, 1 = a move between the user's own accounts. */
  is_internal: number | null;
}

type TransferState =
  | 'not_started' | 'backfilling' | 'idle' | 'error' | 'unsupported' | 'disabled';

interface TransferKindStatus {
  state: TransferState;
  progress_pct: number;
  synced_through?: number;
  backfill_complete?: boolean;
  last_sync_ok_at?: number | null;
  age_seconds?: number | null;
  last_error?: string | null;
  disabled_reason?: string | null;
}

interface TransferConnectionStatus {
  connection_id: number;
  exchange: string;
  label: string | null;
  supported: boolean;
  kinds: Record<'deposit' | 'withdrawal', TransferKindStatus>;
}

interface TransferSyncStatus {
  connections: TransferConnectionStatus[];
  any_pending: boolean;
}

interface TransferPage {
  items: TransferRow[];
  total: number;
  limit: number;
  offset: number;
  sync: TransferSyncStatus;
}

interface TransferSyncResult {
  complete: boolean;
  new_rows: number;
  already_running: boolean;
  sync: TransferSyncStatus;
}
