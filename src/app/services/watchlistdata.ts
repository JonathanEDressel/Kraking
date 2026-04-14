class WatchlistData {
  static async getWatchlist(token: string): Promise<ApiResponse<any[]>> {
    return DataAccess.get<any[]>(
      `${AppConfig.API_BASE}/watchlist/`,
      token
    );
  }

  static async addToWatchlist(token: string, symbol: string): Promise<ApiResponse<any>> {
    return DataAccess.post<any>(
      `${AppConfig.API_BASE}/watchlist/`,
      { symbol },
      token
    );
  }

  static async removeFromWatchlist(token: string, symbol: string): Promise<ApiResponse<any>> {
    return DataAccess.del<any>(
      `${AppConfig.API_BASE}/watchlist/${encodeURIComponent(symbol)}`,
      token
    );
  }
}
