async function openExternalLink(event) {
  if (event.type === 'auxclick' && event.button !== 1) return;
  var link = event.target.closest('a[href]');
  if (!link) return;
  var url = new URL(link.href);
  if (url.origin === location.origin || !['http:', 'https:'].includes(url.protocol)) return;
  event.preventDefault();
  try {
    var response = await fetch('/open-url', {
      method: 'POST', body: new URLSearchParams({url: url.href})
    });
    if (!response.ok) {
      var result = await response.json();
      throw new Error(result.detail || 'The default browser could not be opened');
    }
  } catch (error) {
    alert(error.message);
  }
}
document.addEventListener('click', openExternalLink);
document.addEventListener('auxclick', openExternalLink);
