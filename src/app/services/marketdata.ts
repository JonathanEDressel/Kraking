class MarketData {
  static async getPairs(token: string): Promise<ApiResponse<any[]>> {
    return DataAccess.get<any[]>(
      `${AppConfig.API_BASE}/market/pairs`,
      token
    );
  }

  static async getOHLCV(token: string, symbol: string, range: string): Promise<ApiResponse<any[]>> {
    const params = new URLSearchParams({ symbol, range });
    return DataAccess.get<any[]>(
      `${AppConfig.API_BASE}/market/ohlcv?${params.toString()}`,
      token
    );
  }

  static async getTicker(token: string, symbol: string): Promise<ApiResponse<any>> {
    const params = new URLSearchParams({ symbol });
    return DataAccess.get<any>(
      `${AppConfig.API_BASE}/market/ticker?${params.toString()}`,
      token
    );
  }
}
