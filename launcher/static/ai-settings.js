document.querySelectorAll('form[data-ai-settings]').forEach(form => {
  const status = form.querySelector('[data-ai-status]');
  const value = name => form.querySelector(`[data-ai-field="${name}"]`)?.value || '';
  let revision = 0;
  form.addEventListener('input', () => { revision += 1; });
  const showError = error => { status.textContent = error.message; };
  async function post(url, body) {
    const response = await fetch(url, { method: 'POST', body });
    let result;
    try {
      result = await response.json();
      if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error();
    }
    catch { throw new Error('The launcher returned an unreadable response. Try again.'); }
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not save or look up AI settings.');
    return result;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const body = new FormData(form);
    button.disabled = true;
    status.textContent = 'Saving...';
    try {
      await post(form.action, body);
      window.location.reload();
    } catch (error) { showError(error); }
    finally { button.disabled = false; }
  });
  const autofill = form.querySelector('[data-ai-autofill]');
  if (!autofill) return;
  autofill.addEventListener('click', async () => {
    const context = form.querySelector('[name="context_window_tokens"]');
    if (context.value !== '') {
      status.textContent = 'Keep the entered size, or clear it before using Auto-fill.';
      return;
    }
    const started = ++revision;
    const body = new FormData();
    ['base_url', 'chat_model', 'chat_api_key'].forEach(name => body.set(name, value(name)));
    body.set('keyless', form.querySelector('[name="keyless"]')?.checked ? 'true' : 'false');
    autofill.disabled = true;
    status.textContent = 'Looking up model limits...';
    try {
      const result = await post('/settings/ai/context', body);
      if (revision !== started) {
        status.textContent = 'Settings changed during lookup. Use Auto-fill again if needed.';
        return;
      }
      context.value = result.context_window_tokens;
      status.textContent = 'Conservative allowance suggested from provider metadata. Review it, then Save AI settings.';
    } catch (error) { if (revision === started) showError(error); }
    finally { autofill.disabled = false; }
  });
});
