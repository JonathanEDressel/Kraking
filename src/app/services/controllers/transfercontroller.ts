/**
 * Unwrapping layer over TransferData. Viewmodels call this, never TransferData
 * directly — it is also the seam demo mode patches.
 */
class TransferController {
  static async getTransfers(filters: TransferFilters = {}): Promise<TransferPage> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await TransferData.list(token, filters);
    return response.data;
  }

  static async getStatus(): Promise<TransferSyncStatus> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await TransferData.status(token);
    return response.data;
  }

  /**
   * Run one bounded slice of sync. `complete: false` means there is more
   * history to pull, not that anything went wrong — call again.
   */
  static async sync(connId?: number | 'all'): Promise<TransferSyncResult> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await TransferData.sync(token, connId);
    return response.data;
  }

  static async getAssets(): Promise<string[]> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await TransferData.assets(token);
    return response.data;
  }

  static async getFlow(asset?: string): Promise<TransferFlow> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await TransferData.flow(token, asset);
    return response.data;
  }

  static async rematch(): Promise<MatchSummary> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await TransferData.rematch(token);
    return response.data;
  }

  static async confirmMatch(withdrawalId: number, depositId: number): Promise<void> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    await TransferData.confirmMatch(token, withdrawalId, depositId);
  }

  static async rejectMatch(withdrawalId: number, depositId: number): Promise<void> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    await TransferData.rejectMatch(token, withdrawalId, depositId);
  }

  static async unlockMatch(transferId: number): Promise<void> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    await TransferData.unlockMatch(token, transferId);
  }
}

class WalletController {
  static async getWallets(): Promise<TrackedWallet[]> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await WalletData.list(token);
    return response.data;
  }

  static async getSuggestions(): Promise<WalletSuggestion[]> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await WalletData.suggestions(token);
    return response.data;
  }

  static async createWallet(body: WalletInput): Promise<WalletWriteResult> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await WalletData.create(token, body);
    return response.data;
  }

  static async updateWallet(id: number, body: WalletInput): Promise<WalletWriteResult> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await WalletData.update(token, id, body);
    return response.data;
  }

  static async deleteWallet(id: number): Promise<void> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    await WalletData.remove(token, id);
  }

  static async getTemplate(includeExisting = false): Promise<WalletTemplate> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await WalletData.template(token, includeExisting);
    return response.data;
  }

  static async importFile(filename: string, base64: string,
                          preview: boolean): Promise<WalletImportResult> {
    const token = AuthController.getToken();
    if (!token) throw new Error('Not authenticated');
    const response = await WalletData.importFile(token, filename, base64, preview);
    return response.data;
  }
}
