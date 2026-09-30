(function () {
  var marker = 'openalma-app-window';
  if (new URLSearchParams(window.location.search).get('openalma_app') === '1') {
    sessionStorage.setItem(marker, '1');
  }
  if (sessionStorage.getItem(marker) !== '1') return;

  var previous = '';

  function reportWindowPosition() {
    var state = {
      x: Math.round(window.screenX),
      y: Math.round(window.screenY)
    };
    var body = JSON.stringify(state);
    if (body === previous) return;
    previous = body;
    fetch('/launcher/window-position?' + new URLSearchParams(state), {
      method: 'POST',
      keepalive: true
    });
  }

  setTimeout(reportWindowPosition, 200);
  window.addEventListener('pagehide', reportWindowPosition);
  setInterval(reportWindowPosition, 1000);
})();
