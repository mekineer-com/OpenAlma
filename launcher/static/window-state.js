(function () {
  var key = 'openalma-window-state';
  var marker = 'openalma-app-window';
  if (new URLSearchParams(window.location.search).get('openalma_app') === '1') {
    localStorage.setItem(marker, '1');
  }
  if (localStorage.getItem(marker) !== '1') return;

  var previous = '';

  function reportWindowState() {
    var state = {
      x: Math.round(window.screenX),
      y: Math.round(window.screenY),
      width: Math.round(window.outerWidth),
      height: Math.round(window.outerHeight)
    };
    var body = JSON.stringify(state);
    if (body === previous) return;
    previous = body;
    localStorage.setItem(key, body);
  }

  function startReporting() {
    setTimeout(reportWindowState, 200);
    window.addEventListener('resize', reportWindowState);
    window.addEventListener('pagehide', reportWindowState);
    setInterval(reportWindowState, 1000);
  }

  try {
    var saved = JSON.parse(localStorage.getItem(key));
    if (saved) {
      window.moveTo(saved.x, saved.y);
      window.resizeTo(saved.width, saved.height);
    }
  } catch (_) {}
  startReporting();
})();
