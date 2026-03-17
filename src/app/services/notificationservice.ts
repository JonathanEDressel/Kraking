class NotificationService {
  private static readonly POLL_INTERVAL = 30000; // 30 seconds
  private static timer: number | null = null;
  private static lastSeenLogId: number = 0;
  private static isRunning: boolean = false;
  private static notificationsEnabled: boolean = true;

  static setEnabled(enabled: boolean): void {
    NotificationService.notificationsEnabled = enabled;
  }

  static async start(): Promise<void> {
    if (NotificationService.isRunning) return;

    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
      await Notification.requestPermission();
    }

    NotificationService.isRunning = true;
    NotificationService.pollLogs();
    NotificationService.timer = window.setInterval(
      () => NotificationService.pollLogs(),
      NotificationService.POLL_INTERVAL
    );
  }

  static stop(): void {
    if (NotificationService.timer !== null) {
      window.clearInterval(NotificationService.timer);
      NotificationService.timer = null;
    }
    NotificationService.isRunning = false;
    NotificationService.lastSeenLogId = 0;
  }

  private static async pollLogs(): Promise<void> {
    if (!NotificationService.notificationsEnabled) return;
    try {
      const logs = await AutomationController.getLogs(10);
      
      if (logs.length === 0) return;

      // Initialize with the most recent log ID on first poll
      if (NotificationService.lastSeenLogId === 0) {
        NotificationService.lastSeenLogId = Math.max(...logs.map(l => l.id));
        return;
      }

      // Find new logs (newer than lastSeenLogId)
      const newLogs = logs.filter(l => l.id > NotificationService.lastSeenLogId);
      
      if (newLogs.length === 0) return;

      // Update lastSeenLogId
      NotificationService.lastSeenLogId = Math.max(...logs.map(l => l.id));

      // Show notification for each new log
      for (const log of newLogs) {
        NotificationService.showNotification(log);
      }
    } catch (error) {
      console.error('[NotificationService] Error polling logs:', error);
    }
  }

  private static showNotification(log: any): void {
    if ('Notification' in window && Notification.permission === 'granted') {
      const isSuccess = log.status === 'success';
      const icon = isSuccess ? '✅' : '❌';
      const title = `${icon} Automation Rule ${isSuccess ? 'Executed' : 'Failed'}`;
      
      const body = `${log.action_executed}\n${log.action_result}`;

      const notification = new Notification(title, {
        body: body,
        icon: undefined, // Could add app icon path here if available
        silent: false,
        requireInteraction: false,
      });

      // Close notification after 10 seconds
      setTimeout(() => notification.close(), 10000);

      // Optional: Click to navigate to commands page
      notification.onclick = () => {
        if (typeof router !== 'undefined') {
          router.navigate('commands');
        }
        notification.close();
      };
    }
  }
}
