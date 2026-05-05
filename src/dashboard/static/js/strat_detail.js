function switchStratTab(name) {
  document.querySelectorAll('#strat-tab-nav ~ .tab-panel').forEach(function(p) {
    p.classList.remove('active');
  });
  document.querySelectorAll('#strat-tab-nav button').forEach(function(b) {
    b.classList.remove('active');
  });
  document.getElementById('strat-tab-' + name).classList.add('active');
  document.querySelectorAll('#strat-tab-nav button').forEach(function(b) {
    if (b.getAttribute('onclick') === "switchStratTab('" + name + "')") b.classList.add('active');
  });
  // Render markdown in newly-visible tab if not yet rendered
  var panel = document.getElementById('strat-tab-' + name);
  if (typeof marked !== 'undefined') {
    panel.querySelectorAll('.md-content:not([data-rendered])').forEach(function(el) {
      el.innerHTML = marked.parse(el.textContent);
      el.setAttribute('data-rendered', '1');
    });
  }
  window.location.hash = name;
}
document.addEventListener('DOMContentLoaded', function() {
  // Render markdown in the default active tab
  if (typeof marked !== 'undefined') {
    document.querySelectorAll('.tab-panel.active .md-content').forEach(function(el) {
      el.innerHTML = marked.parse(el.textContent);
      el.setAttribute('data-rendered', '1');
    });
  }
  // Restore tab from URL hash
  var hash = window.location.hash.replace('#', '');
  if (hash && document.getElementById('strat-tab-' + hash)) {
    switchStratTab(hash);
  }
});
