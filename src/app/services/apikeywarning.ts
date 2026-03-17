class ApiKeyWarning {
  private static dismissed = false;

  static init(): void {
    ApiKeyState.onChange(() => ApiKeyWarning.update());

    document.getElementById('api-key-warning-dismiss')?.addEventListener('click', () => {
      ApiKeyWarning.dismissed = true;
      ApiKeyWarning.hide();
    });

    ApiKeyWarning.update();
  }

  static update(): void {
    const status = ApiKeyState.status;

    if (status === 'valid' || status === 'checking' || status === 'unknown') {
      ApiKeyWarning.hide();
      if (status === 'valid') {
        ApiKeyWarning.dismissed = false;
        NotificationService.start();
      }
      return;
    }

    if (ApiKeyWarning.dismissed) return;

    const messageEl = document.getElementById('api-key-warning-message');
    if (!messageEl) return;

    if (status === 'none') {
      messageEl.textContent = 'No exchange connections configured. Add an exchange connection in Settings to enable automation features.';
    } else if (status === 'has_unvalidated') {
      messageEl.textContent = 'Your exchange connection keys have not been validated. Please validate them in Settings.';
    }

    ApiKeyWarning.show();
  }

  private static show(): void {
    document.getElementById('api-key-warning')?.classList.remove('d-none');
  }

  private static hide(): void {
    document.getElementById('api-key-warning')?.classList.add('d-none');
  }
}
