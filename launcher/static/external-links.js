async function openExternalLink(event) {
  if (event.type === 'auxclick' && event.button !== 1) return;
  var link = event.target.closest('a[href]');
  if (!link) return;
  var url = new URL(link.href);
  if (url.origin === location.origin || !['http:', 'https:'].includes(url.protocol)) return;
  event.preventDefault();
  clearLauncherMessage();
  try {
    var response = await fetch('/open-url', {
      method: 'POST', body: new URLSearchParams({url: url.href})
    });
    if (!response.ok) {
      throw new Error(await launcherErrorMessage(response, 'The default browser could not be opened'));
    }
  } catch (error) {
    showLauncherMessage(error.message);
  }
}
document.addEventListener('click', openExternalLink);
document.addEventListener('auxclick', openExternalLink);
