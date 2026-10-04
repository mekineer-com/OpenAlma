async function quitLauncher(button) {
  button.disabled = true;
  try {
    var response = await fetch('/launcher/quit', {method: 'POST'});
    if (!response.ok) throw new Error('Exit failed');
    document.body.innerHTML = '<main><h1>OpenAlma Launcher has exited.</h1><p>You may close this tab.</p></main>';
  } catch (error) {
    button.disabled = false;
    alert(error.message);
  }
}
